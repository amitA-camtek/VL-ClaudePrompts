"""
OpenFGA Authorization Client.

HTTP client for OpenFGA authorization service. Automatically creates store
and deploys authorization model on first use.
"""

import functools
import json
import random
import re
import threading
import time
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx

from vl.common.logging_helpers import get_vl_logger
from vl.common.settings import Settings

logger = get_vl_logger(__name__)


def retry_on_transient_error(max_retries: int = 3, initial_delay: float = 1.0):
    """
    Decorator for retrying on transient HTTP errors (5xx, timeouts).

    Uses exponential backoff with jitter.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_error = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except httpx.HTTPError as e:
                    last_error = e
                    # Only retry on 5xx or timeout errors
                    is_retryable = isinstance(e, httpx.TimeoutException) or (
                        hasattr(e, "response") and e.response is not None and 500 <= e.response.status_code < 600
                    )

                    if not is_retryable or attempt == max_retries:
                        raise

                    jitter = random.uniform(0, delay * 0.1)
                    sleep_time = delay + jitter
                    logger.warning(
                        f"Transient error in {func.__name__}, retrying in {sleep_time:.1f}s "
                        f"(attempt {attempt + 1}/{max_retries}): {e}"
                    )
                    time.sleep(sleep_time)
                    delay *= 2

            raise last_error

        return wrapper

    return decorator


class OpenFGAError(Exception):
    """Exception raised when OpenFGA operations fail."""

    def __init__(self, message: str, status_code: int = None, operation: str = None):
        super().__init__(message)
        self.status_code = status_code
        self.operation = operation


class OpenFGAClient:
    """
    OpenFGA HTTP API client.

    Automatically creates store and deploys model on first use.
    All methods are synchronous for compatibility with existing code.

    Production Safety:
        - Store names are environment-specific to prevent cross-env collisions
        - Production requires explicit OPENFGA_STORE_ID and OPENFGA_MODEL_ID
        - Bootstrap (auto-create) is only allowed in non-production environments
    """

    def __init__(self, base_url: str, timeout: int = 5):
        """
        Initialize the client.

        Args:
            base_url: OpenFGA server URL (e.g., http://localhost:8080)
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._http = httpx.Client(timeout=timeout)
        self._store_id: str | None = None
        self._model_id: str | None = None
        self._initialized = False
        self._noop = False  # True when DISABLE_AUTH is set; all operations become no-ops
        self._init_lock = threading.Lock()

    @classmethod
    def from_settings(cls) -> "OpenFGAClient":
        """Create client from application settings."""
        return cls(base_url=Settings.OPENFGA_API_URL, timeout=Settings.OPENFGA_TIMEOUT_SECONDS)

    @property
    def store_name(self) -> str:
        """Store name - explicit or derived from environment."""
        if Settings.OPENFGA_STORE_NAME:
            return Settings.OPENFGA_STORE_NAME
        env = Settings.ENV_NAME or "local"
        return f"visual-layer-{env}"

    @property
    def store_id(self) -> str:
        """Get store ID, initializing if needed."""
        if not self._initialized:
            self._ensure_store_and_model()
        return self._store_id

    @property
    def model_id(self) -> str:
        """Get model ID, initializing if needed."""
        if not self._initialized:
            self._ensure_store_and_model()
        return self._model_id

    def _ensure_store_and_model(self) -> None:
        """Auto-create store and deploy model if needed. Thread-safe."""
        if self._initialized:
            return

        with self._init_lock:
            if self._initialized:
                return

            if Settings.DISABLE_AUTH:
                self._noop = True
                self._initialized = True
                logger.info("OpenFGA disabled (DISABLE_AUTH=True) — all operations are no-ops")
                return

            if Settings.OPENFGA_STORE_ID:
                self._store_id = Settings.OPENFGA_STORE_ID
                logger.info(
                    "Using configured OpenFGA store", extra={"store_id": self._store_id, "env": Settings.ENV_NAME}
                )
            else:
                if not Settings.OPENFGA_ALLOW_BOOTSTRAP:
                    raise OpenFGAError(
                        "OPENFGA_STORE_ID not set and bootstrap disabled. "
                        "Set OPENFGA_ALLOW_BOOTSTRAP=true for development.",
                        operation="init",
                    )
                self._store_id = self._find_or_create_store()
                logger.info(
                    "Using auto-created OpenFGA store",
                    extra={"store_id": self._store_id, "store_name": self.store_name},
                )

            if Settings.OPENFGA_MODEL_ID:
                self._model_id = Settings.OPENFGA_MODEL_ID
                logger.info(
                    "Using configured OpenFGA model", extra={"model_id": self._model_id, "store_id": self._store_id}
                )
            else:
                if not Settings.OPENFGA_ALLOW_BOOTSTRAP:
                    raise OpenFGAError(
                        "OPENFGA_MODEL_ID not set and bootstrap disabled. "
                        "Set OPENFGA_ALLOW_BOOTSTRAP=true for development.",
                        operation="init",
                    )
                self._model_id = self._ensure_model_deployed()
                logger.info(
                    "Using auto-deployed OpenFGA model", extra={"model_id": self._model_id, "store_id": self._store_id}
                )

            self._initialized = True

    def _find_or_create_store(self) -> str:
        """Find existing store by environment-specific name or create new one."""
        try:
            response = self._http.get(f"{self.base_url}/stores")
            response.raise_for_status()
            stores = response.json().get("stores", [])

            # Look for store with environment-specific name
            for store in stores:
                if store.get("name") == self.store_name:
                    logger.debug(
                        "Found existing OpenFGA store", extra={"store_id": store["id"], "store_name": self.store_name}
                    )
                    return store["id"]

            # Create new store with environment-specific name
            response = self._http.post(f"{self.base_url}/stores", json={"name": self.store_name})
            response.raise_for_status()
            store_id = response.json()["id"]
            logger.info("Created new OpenFGA store", extra={"store_id": store_id, "store_name": self.store_name})
            return store_id

        except httpx.HTTPError as e:
            raise OpenFGAError(
                f"Failed to find/create store '{self.store_name}': {e}", operation="find_or_create_store"
            ) from e

    def _ensure_model_deployed(self) -> str:
        """
        Deploy authorization model and return model ID.

        Always deploys a fresh model to ensure deterministic behavior.
        This avoids the risk of picking models[0] which has undefined order.
        """
        try:
            model_json = self._parse_fga_model()

            # Always deploy - may return existing model ID if identical
            # (behavior is implementation-dependent across OpenFGA versions)
            response = self._http.post(f"{self.base_url}/stores/{self._store_id}/authorization-models", json=model_json)

            # 201 = new model created, 200 = model already exists (some versions)
            if response.status_code in (200, 201):
                model_id = response.json().get("authorization_model_id")
                if model_id:
                    logger.info(
                        "Deployed OpenFGA authorization model", extra={"model_id": model_id, "store_id": self._store_id}
                    )
                    return model_id

            # If deploy didn't return an ID, fetch the latest model
            response.raise_for_status()
            response = self._http.get(f"{self.base_url}/stores/{self._store_id}/authorization-models")
            response.raise_for_status()
            models = response.json().get("authorization_models", [])

            if not models:
                raise OpenFGAError("No authorization models found after deployment", operation="deploy_model")

            # Models are returned in order of creation (newest first)
            model_id = models[0]["id"]
            logger.info(
                "Using latest OpenFGA authorization model", extra={"model_id": model_id, "store_id": self._store_id}
            )
            return model_id

        except httpx.HTTPError as e:
            raise OpenFGAError(f"Failed to deploy model: {e}", operation="deploy_model") from e

    def _parse_fga_model(self) -> dict[str, Any]:
        """
        Parse FGA DSL model file to JSON format.

        Simple parser for the OpenFGA DSL format.

        TODO: Technical debt - this hand-rolled parser is fragile and won't support
        newer DSL features. Consider converting the model.fga to JSON at build time
        using the official `fga model transform` CLI command, or validating the
        model hash after deployment.
        """
        model_path = Path(Settings.OPENFGA_MODEL_PATH)
        if not model_path.is_absolute():
            # Resolve relative path from project root (vl-product directory)
            # Go up from vl/common/openfga_client.py -> vl/common -> vl -> project_root
            project_root = Path(__file__).parent.parent.parent
            model_path = project_root / model_path
        if not model_path.exists():
            raise OpenFGAError(f"Model file not found: {model_path}")

        with open(model_path) as f:
            content = f.read()

        type_definitions = []
        current_type = None
        current_relations = {}  # name -> (parsed_expr, original_string)

        for line in content.split("\n"):
            line = line.strip()

            if not line or line.startswith("#"):
                continue

            if line.startswith("model") or line.startswith("schema"):
                continue

            if line.startswith("type "):
                if current_type:
                    type_def = {"type": current_type}
                    if current_relations:
                        type_def["relations"] = {name: parsed for name, (parsed, _) in current_relations.items()}
                        type_def["metadata"] = {
                            "relations": {
                                name: {"directly_related_user_types": self._extract_user_types(orig_str)}
                                for name, (_, orig_str) in current_relations.items()
                            }
                        }
                    type_definitions.append(type_def)

                current_type = line.split()[1]
                current_relations = {}
                continue

            if line.startswith("define "):
                match = re.match(r"define\s+(\w+):\s*(.+)", line)
                if match:
                    relation_name = match.group(1)
                    relation_expr = match.group(2).strip()
                    # Store both parsed and original string
                    current_relations[relation_name] = (self._parse_relation_expr(relation_expr), relation_expr)

        if current_type:
            type_def = {"type": current_type}
            if current_relations:
                type_def["relations"] = {name: parsed for name, (parsed, _) in current_relations.items()}
                type_def["metadata"] = {
                    "relations": {
                        name: {"directly_related_user_types": self._extract_user_types(orig_str)}
                        for name, (_, orig_str) in current_relations.items()
                    }
                }
            type_definitions.append(type_def)

        return {"schema_version": "1.1", "type_definitions": type_definitions}

    def _parse_relation_expr(self, expr: str) -> dict[str, Any]:
        """Parse a relation expression to JSON format."""
        expr = expr.strip()

        if expr.startswith("["):
            return {"this": {}}

        if " or " in expr:
            parts = [p.strip() for p in expr.split(" or ")]
            return {"union": {"child": [self._parse_relation_expr(p) for p in parts]}}

        if " from " in expr:
            match = re.match(r"(\w+)\s+from\s+(\w+)", expr)
            if match:
                return {
                    "tupleToUserset": {
                        "tupleset": {"relation": match.group(2)},
                        "computedUserset": {"relation": match.group(1)},
                    }
                }

        return {"computedUserset": {"relation": expr}}

    def _extract_user_types(self, expr: str) -> list[dict[str, Any]]:
        """Extract directly related user types from expression."""
        if isinstance(expr, dict):
            return []

        match = re.search(r"\[([^\]]+)\]", expr)
        if match:
            types = match.group(1).split(",")
            result = []
            for t in types:
                t = t.strip()
                if "#" in t:
                    type_name, relation = t.split("#")
                    result.append({"type": type_name, "relation": relation})
                else:
                    result.append({"type": t})
            return result
        return []

    @retry_on_transient_error(max_retries=3, initial_delay=1.0)
    def write_tuple(self, user: str, relation: str, object_type: str, object_id: UUID) -> None:
        """
        Write a relationship tuple to OpenFGA.

        Args:
            user: User identifier (e.g., "user:123e4567-...")
            relation: Relation name (e.g., "viewer", "editor", "owner")
            object_type: Object type (e.g., "dataset")
            object_id: Object UUID
        """
        self._ensure_store_and_model()
        if self._noop:
            return

        try:
            response = self._http.post(
                f"{self.base_url}/stores/{self._store_id}/write",
                json={
                    "writes": {
                        "tuple_keys": [{"user": user, "relation": relation, "object": f"{object_type}:{object_id}"}]
                    }
                },
            )

            # Handle "tuple already exists" error as success (idempotent write)
            if response.status_code == 400:
                try:
                    error_body = response.json()
                    if error_body.get("code") == "write_failed_due_to_invalid_input" and "already exist" in str(
                        error_body.get("message", "")
                    ):
                        logger.debug(
                            "OpenFGA tuple already exists, treating as success",
                            extra={
                                "store_id": self._store_id,
                                "user": user,
                                "relation": relation,
                                "object": f"{object_type}:{object_id}",
                            },
                        )
                        return
                except (json.JSONDecodeError, KeyError):
                    pass  # Let raise_for_status handle it

            response.raise_for_status()
            logger.debug(
                "OpenFGA tuple written",
                extra={
                    "store_id": self._store_id,
                    "user": user,
                    "relation": relation,
                    "object": f"{object_type}:{object_id}",
                },
            )

        except httpx.HTTPError as e:
            raise OpenFGAError(f"Failed to write tuple: {e}", operation="write_tuple") from e

    @retry_on_transient_error(max_retries=3, initial_delay=1.0)
    def delete_tuple(self, user: str, relation: str, object_type: str, object_id: UUID) -> None:
        """
        Delete a relationship tuple from OpenFGA.

        Args:
            user: User identifier (e.g., "user:123e4567-...")
            relation: Relation name (e.g., "viewer", "editor", "owner")
            object_type: Object type (e.g., "dataset")
            object_id: Object UUID
        """
        self._ensure_store_and_model()
        if self._noop:
            return

        try:
            response = self._http.post(
                f"{self.base_url}/stores/{self._store_id}/write",
                json={
                    "deletes": {
                        "tuple_keys": [{"user": user, "relation": relation, "object": f"{object_type}:{object_id}"}]
                    }
                },
            )
            if response.status_code == 400:
                error_body = response.text
                raise OpenFGAError(f"Delete failed (400): {error_body}", status_code=400, operation="delete_tuple")
            response.raise_for_status()
            logger.debug(
                "OpenFGA tuple deleted",
                extra={
                    "store_id": self._store_id,
                    "user": user,
                    "relation": relation,
                    "object": f"{object_type}:{object_id}",
                },
            )

        except httpx.HTTPError as e:
            raise OpenFGAError(f"Failed to delete tuple: {e}", operation="delete_tuple") from e

    @retry_on_transient_error(max_retries=3, initial_delay=1.0)
    def read_tuples_by_type(
        self,
        object_type: str,
        page_size: int = 100,
    ) -> list[dict[str, str]]:
        """
        Read all tuples for an object type with pagination.

        Args:
            object_type: Object type (e.g., "workspace")
            page_size: Number of tuples per page

        Returns:
            List of all tuples with keys: user, relation, object
        """
        self._ensure_store_and_model()
        if self._noop:
            return []

        all_tuples = []
        continuation_token = None

        try:
            while True:
                # Read all tuples, then filter by type
                # OpenFGA Read API doesn't support type-only filtering with "type:"
                body: dict = {"page_size": page_size}
                if continuation_token:
                    body["continuation_token"] = continuation_token

                response = self._http.post(
                    f"{self.base_url}/stores/{self._store_id}/read",
                    json=body,
                )
                response.raise_for_status()

                data = response.json()
                tuples = data.get("tuples", [])

                # Filter tuples by object type (object format is "type:id")
                for t in tuples:
                    key = t.get("key", {})
                    obj = key.get("object", "")
                    if obj.startswith(f"{object_type}:"):
                        all_tuples.append(key)

                continuation_token = data.get("continuation_token")
                if not continuation_token:
                    break

            return all_tuples

        except httpx.HTTPError as e:
            raise OpenFGAError(f"Failed to read tuples by type: {e}", operation="read_tuples_by_type") from e

    @retry_on_transient_error(max_retries=3, initial_delay=1.0)
    def read_tuples(
        self,
        relation: str,
        object_type: str,
        object_id: UUID,
        user: str | None = None,
    ) -> list[dict[str, str]]:
        """
        Read relationship tuples from OpenFGA.

        Args:
            relation: Relation name (e.g., "admin", "editor", "viewer")
            object_type: Object type (e.g., "workspace")
            object_id: Object UUID
            user: Optional user filter (e.g., "user:123e4567-...")

        Returns:
            List of matching tuples, each with keys: user, relation, object
        """
        self._ensure_store_and_model()
        if self._noop:
            return []

        try:
            tuple_key = {
                "relation": relation,
                "object": f"{object_type}:{object_id}",
            }
            if user:
                tuple_key["user"] = user

            response = self._http.post(
                f"{self.base_url}/stores/{self._store_id}/read",
                json={"tuple_key": tuple_key},
            )
            response.raise_for_status()

            data = response.json()
            tuples = data.get("tuples", [])
            return [t.get("key", {}) for t in tuples]

        except httpx.HTTPError as e:
            raise OpenFGAError(f"Failed to read tuples: {e}", operation="read_tuples") from e

    @retry_on_transient_error(max_retries=3, initial_delay=1.0)
    def write_tuples_batch(self, tuples: list[dict[str, Any]], batch_size: int = 100) -> int:
        """
        Write multiple tuples in batches with compensation on failure.

        If a batch fails, previously written batches are deleted to maintain
        consistency with PostgreSQL (which will rollback).

        Note: Retry decorator is safe because OpenFGA handles duplicate
        tuples with 409, which we treat as success.

        Args:
            tuples: List of tuple dicts with keys: user, relation, object
            batch_size: Number of tuples per batch

        Returns:
            Number of tuples written
        """
        self._ensure_store_and_model()
        if self._noop:
            return 0

        written_tuples = []

        try:
            for i in range(0, len(tuples), batch_size):
                batch = tuples[i : i + batch_size]
                response = self._http.post(
                    f"{self.base_url}/stores/{self._store_id}/write", json={"writes": {"tuple_keys": batch}}
                )

                if response.status_code == 409:
                    logger.debug(
                        "OpenFGA batch contained existing tuples",
                        extra={"store_id": self._store_id, "batch_size": len(batch)},
                    )
                    written_tuples.extend(batch)
                    continue

                if response.status_code == 400:
                    # Check if error is "tuple already exists" - write one-by-one to skip duplicates
                    try:
                        error_body = response.json()
                        if error_body.get("code") == "write_failed_due_to_invalid_input" and "already exist" in str(
                            error_body.get("message", "")
                        ):
                            logger.debug(
                                "OpenFGA batch has duplicates, falling back to one-by-one writes",
                                extra={"store_id": self._store_id, "batch_size": len(batch)},
                            )
                            # Write tuples one-by-one, skipping ones that already exist
                            skipped_existing = 0
                            for t in batch:
                                single_response = self._http.post(
                                    f"{self.base_url}/stores/{self._store_id}/write",
                                    json={"writes": {"tuple_keys": [t]}},
                                )
                                if single_response.status_code in (200, 201):
                                    written_tuples.append(t)
                                elif single_response.status_code == 400:
                                    # Check if tuple already exists
                                    try:
                                        single_error = single_response.json()
                                        if "already exist" in str(single_error.get("message", "")):
                                            skipped_existing += 1
                                            written_tuples.append(t)  # Count as "written" since state is correct
                                            continue
                                    except (json.JSONDecodeError, KeyError):
                                        pass
                                    single_response.raise_for_status()
                                else:
                                    single_response.raise_for_status()
                            if skipped_existing > 0:
                                logger.debug(
                                    f"Skipped {skipped_existing} existing tuples in batch",
                                    extra={"store_id": self._store_id, "batch_size": len(batch)},
                                )
                            continue
                    except (json.JSONDecodeError, KeyError):
                        pass  # Not a JSON response or unexpected format, let raise_for_status handle it

                response.raise_for_status()
                written_tuples.extend(batch)
                logger.debug(
                    "OpenFGA batch written",
                    extra={
                        "store_id": self._store_id,
                        "batch_size": len(batch),
                        "total_written": len(written_tuples),
                        "total_tuples": len(tuples),
                    },
                )

            return len(written_tuples)

        except httpx.HTTPError as e:
            if written_tuples:
                logger.warning(
                    f"Batch write failed after {len(written_tuples)} tuples, compensating by deleting written tuples"
                )
                self._compensate_failed_batch(written_tuples)
            raise OpenFGAError(f"Failed to write tuple batch: {e}", operation="write_tuples_batch") from e

    def _compensate_failed_batch(self, tuples: list[dict[str, Any]]) -> None:
        """
        Best-effort deletion of tuples written before a batch failure.

        Errors are logged but not raised (compensation is best-effort).
        Uses longer timeout since this is cleanup code.
        Failed tuples are logged with an error ID for Sentry tracking and reconciliation.
        """
        error_id = str(uuid4())[:8]  # Short unique ID for tracking
        failed_tuples = []

        try:
            with httpx.Client(timeout=30) as client:
                for i in range(0, len(tuples), 100):
                    batch = tuples[i : i + 100]
                    response = client.post(
                        f"{self.base_url}/stores/{self._store_id}/write", json={"deletes": {"tuple_keys": batch}}
                    )
                    if response.status_code == 200:
                        logger.info(f"Compensation [{error_id}]: deleted {len(batch)} tuples")
                    else:
                        failed_tuples.extend(batch)
                        logger.warning(
                            f"Compensation [{error_id}]: delete returned {response.status_code}: {response.text}"
                        )
        except Exception as e:
            failed_tuples.extend(tuples)
            logger.error(f"Compensation [{error_id}]: delete failed: {e}")

        if failed_tuples:
            logger.error(
                f"Compensation [{error_id}]: {len(failed_tuples)} tuples could not be deleted. "
                f"Manual reconciliation may be required. Tuples: {json.dumps(failed_tuples[:10])}..."
                if len(failed_tuples) > 10
                else f"Compensation [{error_id}]: {len(failed_tuples)} tuples could not be deleted. "
                f"Manual reconciliation may be required. Tuples: {json.dumps(failed_tuples)}"
            )

    def delete_tuples_batch(self, tuples: list[dict[str, Any]], batch_size: int = 100) -> int:
        """
        Delete multiple tuples in batches.

        Args:
            tuples: List of tuple dicts with keys: user, relation, object
            batch_size: Number of tuples per batch

        Returns:
            Number of tuples deleted
        """
        self._ensure_store_and_model()
        if self._noop:
            return 0

        total_deleted = 0
        for i in range(0, len(tuples), batch_size):
            batch = tuples[i : i + batch_size]

            try:
                response = self._http.post(
                    f"{self.base_url}/stores/{self._store_id}/write", json={"deletes": {"tuple_keys": batch}}
                )
                response.raise_for_status()
                total_deleted += len(batch)
                logger.debug(
                    "OpenFGA batch deleted",
                    extra={
                        "store_id": self._store_id,
                        "batch_size": len(batch),
                        "total_deleted": total_deleted,
                        "total_tuples": len(tuples),
                    },
                )

            except httpx.HTTPError as e:
                raise OpenFGAError(f"Failed to delete tuple batch: {e}", operation="delete_tuples_batch") from e

        return total_deleted

    @retry_on_transient_error(max_retries=3, initial_delay=1.0)
    def check_permission(self, user: str, relation: str, object_type: str, object_id: UUID) -> bool:
        """
        Check if user has a permission on an object.

        Args:
            user: User identifier (e.g., "user:123e4567-...")
            relation: Permission to check (e.g., "can_view", "can_edit")
            object_type: Object type (e.g., "dataset")
            object_id: Object UUID

        Returns:
            True if user has the permission
        """
        self._ensure_store_and_model()
        if self._noop:
            return True

        try:
            response = self._http.post(
                f"{self.base_url}/stores/{self._store_id}/check",
                json={
                    "tuple_key": {"user": user, "relation": relation, "object": f"{object_type}:{object_id}"},
                    "authorization_model_id": self._model_id,
                },
            )
            response.raise_for_status()
            allowed = response.json().get("allowed", False)
            logger.debug(
                "OpenFGA permission check",
                extra={
                    "store_id": self._store_id,
                    "user": user,
                    "relation": relation,
                    "object": f"{object_type}:{object_id}",
                    "allowed": allowed,
                },
            )
            return allowed

        except httpx.HTTPError as e:
            raise OpenFGAError(f"Failed to check permission: {e}", operation="check_permission") from e

    def check_permissions_batch(
        self,
        user: str,
        relations: list[str],
        object_type: str,
        object_id: UUID,
        max_workers: int = 10,
    ) -> dict[str, bool]:
        """
        Check multiple permissions for the same user and object in parallel.

        Uses ThreadPoolExecutor for parallelization.

        Args:
            user: User identifier (e.g., "user:123e4567-...")
            relations: List of permissions to check (e.g., ["can_view", "can_edit"])
            object_type: Object type (e.g., "dataset")
            object_id: Object UUID
            max_workers: Maximum number of concurrent workers

        Returns:
            Dict mapping permission name to boolean allowed status
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        self._ensure_store_and_model()
        if self._noop:
            return {rel: True for rel in relations}

        results: dict[str, bool] = {}

        def check_single(relation: str) -> tuple[str, bool]:
            try:
                allowed = self.check_permission(user, relation, object_type, object_id)
                return (relation, allowed)
            except OpenFGAError as e:
                logger.warning(f"Permission check failed for {relation}: {e}")
                return (relation, False)

        with ThreadPoolExecutor(max_workers=min(max_workers, len(relations))) as executor:
            futures = {executor.submit(check_single, rel): rel for rel in relations}

            for future in as_completed(futures):
                relation, allowed = future.result()
                results[relation] = allowed

        return results


# Singleton instance
_client: OpenFGAClient | None = None


def get_openfga_client() -> OpenFGAClient:
    """Get the singleton OpenFGA client instance."""
    global _client
    if _client is None:
        _client = OpenFGAClient.from_settings()
    return _client
