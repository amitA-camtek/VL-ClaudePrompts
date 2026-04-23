import asyncio
import ntpath
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Annotated, List, Optional

from fastapi import APIRouter, HTTPException, Query, Security
from pydantic import BaseModel

from clustplorer.logic.data_server.common import _get_data_server_client
from clustplorer.logic.feature_checks import new_status_enabled
from clustplorer.web.auth import get_authenticated_user
from providers.camtek.DataServerClient import (
    FilterForScanResults,
    ReloadStatus,
    RepositorySource,
)
from vl.common.logging_helpers import get_vl_logger
from vl.common.settings import Settings
from vldbaccess.base import DatasetSourceType, DatasetStatus, NewDatasetStatus
from vldbaccess.dataset import DatasetDB
from vldbaccess.dataset_folders_dao import DatasetFoldersDAO
from vldbaccess.models.dataset_folder import FolderStatus
from vldbaccess.user import User, get_user_default_org_workspace_sync
from clustplorer.logic.process_dataset_folder_task.process_dataset_folder_task_impl import ProcessDatasetFolderTask

logger = get_vl_logger(__name__)

router = APIRouter(tags=["scan-results"])


# ── Pydantic models ───────────────────────────────────────────────────────────

class RepositorySourceSchema(BaseModel):
    id: Optional[str] = None
    name: str
    path: str
    user_name: Optional[str] = None
    password: Optional[str] = None
    server_name: Optional[str] = None
    is_enabled: bool = True

    class Config:
        from_attributes = True


class ScanProcessStatusSchema(BaseModel):
    value: int
    name: str


class YieldDataSchema(BaseModel):
    good_dice_count: int = 0
    bad_dice_count: int = 0


class ScannedYieldDataSchema(BaseModel):
    yield_data: Optional[YieldDataSchema] = None
    scanned_dice_count: int = 0


class WaferSchema(BaseModel):
    wafer_id: str = ""
    lot_id: str = ""


class SetupSchema(BaseModel):
    setup_name: str = ""
    job_name: str = ""
    job_tag: str = ""


class ScanProcessSchema(BaseModel):
    wafer: Optional[WaferSchema] = None
    machine_name: str = ""
    setup: Optional[SetupSchema] = None
    scan_start_time: Optional[str] = None
    scan_process_status: int = 0
    scan_process_status_name: str = "ScanStarted"


class WaferScanResultSchema(BaseModel):
    scan_process: Optional[ScanProcessSchema] = None
    number_of_defects_after_scan: int = 0
    number_of_defects_after_verification: int = 0
    import_yield_data: Optional[YieldDataSchema] = None
    scanned_yield_data: Optional[ScannedYieldDataSchema] = None
    verify_yield_data: Optional[YieldDataSchema] = None
    path_to_files: str = ""
    is_locked: bool = False
    locked_by_user: str = ""
    reason: str = ""
    origin: int = 0
    origin_name: str = "Normal"
    source_name: str = ""
    source_id: str = ""
    verification_state: int = 0
    verification_state_name: str = "NotRequired"


class ScanResultsResponse(BaseModel):
    count: int
    items: List[WaferScanResultSchema]


class ReloadStatusResponse(BaseModel):
    status: int
    status_name: str


class BoolResponse(BaseModel):
    result: bool


class ValidateRepositoryRequest(BaseModel):
    repository: RepositorySourceSchema


class ExportDatasetRequest(BaseModel):
    scan_result_paths: List[str]
    dataset_name: str
    export_path: str = ""


class ExportDatasetResponse(BaseModel):
    dataset_id: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_repo(schema: RepositorySourceSchema) -> RepositorySource:
    return RepositorySource(
        id=schema.id or "",
        name=schema.name,
        path=schema.path,
        user_name=schema.user_name or "",
        password=schema.password or "",
        server_name=schema.server_name or "",
        is_enabled=schema.is_enabled,
    )


def _from_repo(repo: RepositorySource) -> RepositorySourceSchema:
    return RepositorySourceSchema(
        id=repo.id,
        name=repo.name,
        path=repo.path,
        user_name=repo.user_name,
        password="",
        server_name=repo.server_name,
        is_enabled=repo.is_enabled,
    )


def _serialize_wafer_scan_result(wsr) -> WaferScanResultSchema:
    sp = wsr.scan_process
    scan_process = None
    if sp:
        scan_process = ScanProcessSchema(
            wafer=WaferSchema(
                wafer_id=sp.wafer.wafer_id if sp.wafer else "",
                lot_id=sp.wafer.lot_id if sp.wafer else "",
            ) if sp.wafer else None,
            machine_name=sp.machine_name,
            setup=SetupSchema(
                setup_name=sp.setup.setup_name if sp.setup else "",
                job_name=sp.setup.job_name if sp.setup else "",
                job_tag=sp.setup.job_tag if sp.setup else "",
            ) if sp.setup else None,
            scan_start_time=sp.scan_start_time.isoformat() if sp.scan_start_time else None,
            scan_process_status=int(sp.scan_process_status),
            scan_process_status_name=sp.scan_process_status.name if sp.scan_process_status else "ScanStarted",
        )
    return WaferScanResultSchema(
        scan_process=scan_process,
        number_of_defects_after_scan=wsr.number_of_defects_after_scan,
        number_of_defects_after_verification=wsr.number_of_defects_after_verification,
        import_yield_data=YieldDataSchema(
            good_dice_count=wsr.import_yield_data.good_dice_count,
            bad_dice_count=wsr.import_yield_data.bad_dice_count,
        ) if wsr.import_yield_data else None,
        scanned_yield_data=ScannedYieldDataSchema(
            yield_data=YieldDataSchema(
                good_dice_count=wsr.scanned_yield_data.yield_data.good_dice_count,
                bad_dice_count=wsr.scanned_yield_data.yield_data.bad_dice_count,
            ) if wsr.scanned_yield_data and wsr.scanned_yield_data.yield_data else None,
            scanned_dice_count=wsr.scanned_yield_data.scanned_dice_count if wsr.scanned_yield_data else 0,
        ) if wsr.scanned_yield_data else None,
        verify_yield_data=YieldDataSchema(
            good_dice_count=wsr.verify_yield_data.good_dice_count,
            bad_dice_count=wsr.verify_yield_data.bad_dice_count,
        ) if wsr.verify_yield_data else None,
        path_to_files=wsr.path_to_files,
        is_locked=wsr.is_locked,
        locked_by_user=wsr.locked_by_user,
        reason=wsr.reason,
        origin=int(wsr.origin),
        origin_name=wsr.origin.name if wsr.origin is not None else "Normal",
        source_name=wsr.source_name,
        source_id=wsr.source_id,
        verification_state=int(wsr.verification_state),
        verification_state_name=wsr.verification_state.name if wsr.verification_state is not None else "NotRequired",
    )


# ── Export endpoint ──────────────────────────────────────────────────────────

@router.post("/api/v1/scan-results/export-dataset")
async def export_to_dataset(
    user: Annotated[User, Security(get_authenticated_user, use_cache=False)],
    body: ExportDatasetRequest,
) -> ExportDatasetResponse:
    if not body.scan_result_paths:
        raise HTTPException(status_code=400, detail="No scan result paths provided")
    if not body.dataset_name or not body.dataset_name.strip():
        raise HTTPException(status_code=400, detail="Dataset name is required")
    if not body.export_path or not body.export_path.strip():
        raise HTTPException(status_code=400, detail="Export path is required")
    try:
        organization_id, workspace_id = get_user_default_org_workspace_sync(user)

        # 1. Validate same recipes (matching MDC's ValidateScanResultsHaveSameRecipes check)
        client = _get_data_server_client()
        logger.info(f"ValidateScanResultsHaveSameRecipes — paths: {body.scan_result_paths}")
        recipe_validation = await asyncio.to_thread(
            client.validate_scan_results_have_same_recipes, body.scan_result_paths
        )
        logger.info(f"ValidateScanResultsHaveSameRecipes — is_valid={recipe_validation.is_valid!r}, message={recipe_validation.message!r}")
        if not recipe_validation.is_valid:
            reason = recipe_validation.message.strip() or "Selected scan results have different recipes. Please select scan results that use the same recipe."
            raise HTTPException(
                status_code=400,
                detail=f"Export ADC — Recipe Validation Error: {reason}",
            )

        # 2. Validate same ManReClassify (matching MDC's ValidateScanResultsHaveSameManReClassify check)
        logger.info(f"ValidateScanResultsHaveSameManReClassify — paths: {body.scan_result_paths}")
        try:
            man_re_classify_validation = await asyncio.to_thread(
                client.validate_scan_results_have_same_man_re_classify, body.scan_result_paths
            )
            logger.info(f"ValidateScanResultsHaveSameManReClassify — is_valid={man_re_classify_validation.is_valid!r}, message={man_re_classify_validation.message!r}")
            if not man_re_classify_validation.is_valid:
                reason = man_re_classify_validation.message.strip() or "Selected scan results have different manual reclassification settings. Please select scan results with the same ManReClassify configuration."
                raise HTTPException(
                    status_code=400,
                    detail=f"Export ADC — ManReClassify Validation Error: {reason}",
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"ValidateScanResultsHaveSameManReClassify failed with exception: {e} — skipping, proceeding with export")

        # 3. Export via Data Server gRPC
        logger.info(
            f"Starting ExportADC for {len(body.scan_result_paths)} scan results "
            f"to '{body.export_path}'"
        )
        export_started_at = time.time()
        result = await asyncio.to_thread(
            client.export_adc, body.scan_result_paths, body.export_path
        )
        if not result.success:
            raise HTTPException(
                status_code=500,
                detail=f"ExportADC failed: {result.error_message or 'unknown error'}",
            )
        logger.info(
            f"ExportADC completed: path={result.export_path}, "
            f"wafers={result.wafers_exported}, defects={result.defects_exported}"
        )

        # 4. Resolve the exported subfolder path
        datasets_dir = Settings.DATASETS_CREATION_DIRECTORY or ""
        base_folder = ntpath.basename(body.export_path.rstrip("\\/"))
        mount_base = os.path.join(datasets_dir, base_folder) if datasets_dir else ""

        if result.export_path:
            # C# fix: ExportPath is now returned directly — extract the subfolder name
            exported_subfolder = ntpath.basename(result.export_path.rstrip("\\/"))
            logger.info(f"Using ExportPath from gRPC response: {result.export_path} → subfolder: {exported_subfolder}")
        else:
            # Fallback: detect newest subfolder created during export (timestamp-based)
            logger.warning("ExportPath not set in gRPC response — falling back to timestamp-based subfolder detection")
            if not mount_base or not os.path.isdir(mount_base):
                raise HTTPException(
                    status_code=500,
                    detail=f"Export mount not found: {mount_base}. Check DATASETS_CREATION_DIRECTORY.",
                )
            new_subdirs = [
                d for d in os.scandir(mount_base)
                if d.is_dir() and d.stat().st_mtime >= export_started_at
            ]
            if not new_subdirs:
                raise HTTPException(status_code=500, detail="ExportADC produced no output subfolder.")
            exported_subfolder = max(new_subdirs, key=lambda d: d.stat().st_mtime).name

        # Copy exported subfolder to the datasets root so the image proxy and pipeline can serve it.
        # Prefer DATASETS_CREATION_DIRECTORY (pod-internal mount) if it exists on the filesystem;
        # fall back to DATASETS_HOST_PATH for the host-side debug case.
        _creation_dir = Settings.DATASETS_CREATION_DIRECTORY or ""
        _host_path = Settings.DATASETS_HOST_PATH or ""
        if _creation_dir and os.path.isdir(_creation_dir):
            host_dir = _creation_dir
        elif _host_path and os.path.isdir(_host_path):
            host_dir = _host_path
        else:
            raise HTTPException(status_code=500, detail="DATASETS_HOST_PATH is not configured")
        cifs_source = os.path.join(host_dir, base_folder, exported_subfolder)
        local_dest = os.path.join(host_dir, exported_subfolder)
        if os.path.exists(local_dest):
            logger.info(f"Local copy already exists at {local_dest!r} — skipping copy")
        else:
            if not os.path.exists(cifs_source):
                raise HTTPException(status_code=500, detail=f"Export source not found: {cifs_source}")
            logger.info(f"Copying exported data from CIFS {cifs_source!r} to local {local_dest!r}")
            await asyncio.to_thread(shutil.copytree, cifs_source, local_dest)
            logger.info(f"Copy complete: {local_dest!r}")

        logger.info(f"Exported subfolder: {exported_subfolder}")

        # source_uri must point to the PARENT of the exported subfolder in pod-path terms.
        # The pipeline's dirs_to_skip() logic checks immediate subdirs of DATASET_SOURCE_DIR
        # against SELECTED_FOLDERS (= [exported_subfolder name]).
        # With the copy, the subfolder is directly under /datasets, so source_uri = /datasets.
        if datasets_dir:
            source_uri = datasets_dir
        elif result.export_path and result.export_path.startswith("/"):
            source_uri = str(Path(result.export_path).parent.parent)
        else:
            source_uri = ""
        logger.info(f"Dataset source_uri resolved to: {source_uri!r}")

        # 5. Create dataset record
        ds = DatasetDB.create(
            created_by=user.user_id,
            owned_by="VL",
            display_name=body.dataset_name.strip(),
            status=DatasetStatus.NEW,
            status_new=NewDatasetStatus.DRAFT,
            preview_uri="",
            source_uri=source_uri,
            source_type=DatasetSourceType.LOCAL_DISK,
            serve_mode=DatasetDB.determine_serve_mode_from_settings(),
            organization_id=organization_id,
            workspace_id=workspace_id,
            uses_status_v2=new_status_enabled(user),
        )
        logger.info(
            f"Created dataset {ds.dataset_id} ('{body.dataset_name}') for user {user.user_id}"
        )

        # 6. Ingest the exported folder into VL
        folder_id = DatasetFoldersDAO.create_folder(
            dataset_id=ds.dataset_id,
            folder_name=exported_subfolder,
            status=FolderStatus.VALIDATING,
            total_files=0,
        )
        # DatasetLocalFolderProvider resolves: Path(DATASETS_CREATION_DIRECTORY) / path.
        # When path is absolute, pathlib ignores the base, so passing the host-accessible
        # absolute path works whether this runs on the host (debug) or inside the pod (deployed).
        await ProcessDatasetFolderTask(folder_id, local_dest).run()
        logger.info(f"Ingestion complete for dataset {ds.dataset_id}, folder {exported_subfolder}")

        return ExportDatasetResponse(dataset_id=str(ds.dataset_id))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to export scan results to dataset: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Export failed: {e}")


# ── Repository endpoints ──────────────────────────────────────────────────────

@router.get("/api/v1/scan-results/repositories")
async def get_repositories(
    user: Annotated[User, Security(get_authenticated_user, use_cache=False)],
) -> List[RepositorySourceSchema]:
    client = None
    try:
        client = _get_data_server_client()
        repos = client.get_repositories()
        return [_from_repo(r) for r in repos]
    except Exception as e:
        logger.error(f"Failed to get repositories: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get repositories")
    finally:
        if client:
            client.close()


@router.post("/api/v1/scan-results/repositories")
async def add_repository(
    user: Annotated[User, Security(get_authenticated_user, use_cache=False)],
    body: RepositorySourceSchema,
) -> BoolResponse:
    client = None
    try:
        repo = _to_repo(body)
        if not repo.id:
            repo.id = str(uuid.uuid4())
        client = _get_data_server_client()
        result = client.add_repository(repo)
        return BoolResponse(result=result)
    except Exception as e:
        logger.error(f"Failed to add repository: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to add repository")
    finally:
        if client:
            client.close()


@router.put("/api/v1/scan-results/repositories/{repo_id}")
async def edit_repository(
    user: Annotated[User, Security(get_authenticated_user, use_cache=False)],
    repo_id: str,
    body: RepositorySourceSchema,
) -> BoolResponse:
    client = None
    try:
        repo = _to_repo(body)
        repo.id = repo_id
        client = _get_data_server_client()
        result = client.edit_repository(repo)
        return BoolResponse(result=result)
    except Exception as e:
        logger.error(f"Failed to edit repository {repo_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to edit repository")
    finally:
        if client:
            client.close()


@router.delete("/api/v1/scan-results/repositories/{repo_id}")
async def delete_repository(
    user: Annotated[User, Security(get_authenticated_user, use_cache=False)],
    repo_id: str,
) -> BoolResponse:
    client = None
    try:
        client = _get_data_server_client()
        result = client.delete_repository(repo_id)
        return BoolResponse(result=result)
    except Exception as e:
        logger.error(f"Failed to delete repository {repo_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete repository")
    finally:
        if client:
            client.close()


@router.post("/api/v1/scan-results/repositories/validate")
async def validate_repository(
    user: Annotated[User, Security(get_authenticated_user, use_cache=False)],
    body: ValidateRepositoryRequest,
) -> ReloadStatusResponse:
    client = None
    try:
        client = _get_data_server_client()
        status = client.validate_repository(_to_repo(body.repository))
        return ReloadStatusResponse(status=int(status), status_name=status.name)
    except Exception as e:
        logger.error(f"Failed to validate repository: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to validate repository")
    finally:
        if client:
            client.close()


@router.post("/api/v1/scan-results/reload-all")
async def reload_all_repositories(
    user: Annotated[User, Security(get_authenticated_user, use_cache=False)],
) -> ReloadStatusResponse:
    client = None
    try:
        client = _get_data_server_client()
        response = client.reload_enabled_repositories()
        status = response.general_status
        return ReloadStatusResponse(status=int(status), status_name=status.name)
    except Exception as e:
        logger.error(f"Failed to reload enabled repositories: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to reload repositories")
    finally:
        if client:
            client.close()


# ── Scan results endpoints ─────────────────────────────────────────────────────

@router.get("/api/v1/scan-results")
async def get_scan_results(
    user: Annotated[User, Security(get_authenticated_user, use_cache=False)],
    job: Optional[str] = Query(default=None),
    lot: Optional[str] = Query(default=None),
    setup: Optional[str] = Query(default=None),
    repository_id: Optional[str] = Query(default=None),
    max_count: Optional[int] = Query(default=None),
) -> ScanResultsResponse:
    client = None
    try:
        filter_ = FilterForScanResults(
            job=job or "",
            lot=lot or "",
            setup=setup or "",
            repository_id=repository_id or "",
            max_scan_results_count=max_count,
        )
        client = _get_data_server_client()
        response = client.get_scan_results_by_filter(filter_)
        return ScanResultsResponse(
            count=response.count,
            items=[_serialize_wafer_scan_result(r) for r in response.wafer_scan_results],
        )
    except Exception as e:
        logger.error(f"Failed to get scan results: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get scan results")
    finally:
        if client:
            client.close()


@router.get("/api/v1/scan-results/filter/devices")
async def get_devices_names(
    user: Annotated[User, Security(get_authenticated_user, use_cache=False)],
    repository_id: Optional[str] = Query(default=None),
) -> List[str]:
    client = None
    try:
        filter_ = FilterForScanResults(repository_id=repository_id or "")
        client = _get_data_server_client()
        return client.get_devices_names(filter_)
    except Exception as e:
        logger.error(f"Failed to get device names: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get device names")
    finally:
        if client:
            client.close()


@router.get("/api/v1/scan-results/filter/setups")
async def get_setups_names(
    user: Annotated[User, Security(get_authenticated_user, use_cache=False)],
    repository_id: Optional[str] = Query(default=None),
) -> List[str]:
    client = None
    try:
        filter_ = FilterForScanResults(repository_id=repository_id or "")
        client = _get_data_server_client()
        return client.get_setups_names(filter_)
    except Exception as e:
        logger.error(f"Failed to get setup names: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get setup names")
    finally:
        if client:
            client.close()


@router.get("/api/v1/scan-results/filter/lots")
async def get_lots_names(
    user: Annotated[User, Security(get_authenticated_user, use_cache=False)],
    repository_id: Optional[str] = Query(default=None),
) -> List[str]:
    client = None
    try:
        filter_ = FilterForScanResults(repository_id=repository_id or "")
        client = _get_data_server_client()
        return client.get_lots_names(filter_)
    except Exception as e:
        logger.error(f"Failed to get lot names: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get lot names")
    finally:
        if client:
            client.close()
