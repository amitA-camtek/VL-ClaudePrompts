# VL Developer Guide

This guide walks you through setting up a local development environment for the Visual Layer backend
(`clustplorer`) and connecting it to a k3s cluster running on the same machine.

> **Before you start**: You must already have a working CPU installation of the VL system (k3s with
> PostgreSQL, Keycloak, and OpenFGA deployed). If you don't, stop here and complete the installation first.

---

## 1. Prerequisites

Make sure all of the following are installed on your machine. If any are missing, install them before continuing.

| Tool | How to check | Install if missing |
|---|---|---|
| Python 3.10 | `python3.10 --version` | `sudo apt install python3.10` |
| uv (Python package manager) | `uv --version` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| PostgreSQL client | `psql --version` | `sudo apt install postgresql-client` |
| kubectl | `kubectl version --client` | Should already be installed with k3s |
| VSCode | Open it | Download from https://code.visualstudio.com |

---

## 2. Building the Virtual Environment

Run these commands **from the repo root directory**, one at a time. Do not skip any step.

```bash
# Step 1: Create the virtual environment
pip3.10 install -U uv pip
uv venv -p 3.10 .venv

# Step 2: Activate it (you must do this every time you open a new terminal)
. .venv/bin/activate

# Step 3: Install dependencies (this takes a few minutes)
uv pip install -r requirements_no_dependencies.txt --no-deps
uv pip install -r requirements.txt -r requirements_dev.txt -r requirements_preprocessing.txt -r requirements_preprocessing_cpu.txt ipython
uv pip install -r requirements_be.txt

# Step 4: Build the C++ extensions
python setup.py build_ext --inplace
# Step 5. Pre-install DuckDB extensions (bypasses proxy issues)
info "Installing DuckDB extensions..."
duckdb_version=$(python -c "import duckdb; print(duckdb.__version__)")
echo "  DuckDB version: $duckdb_version"

ext_dir="/tmp/duckdb-extensions"
mkdir -p "$ext_dir"
for ext in vss fts postgres_scanner; do
   ext_url="http://extensions.duckdb.org/v${duckdb_version}/linux_amd64/${ext}.duckdb_extension.gz"
   echo "Downloading ${ext}..."
   wget -q -O "${ext_dir}/${ext}.duckdb_extension.gz" "$ext_url"
done
```

### Verify it worked

Open an `ipython` console (type `ipython` in the terminal) and run:

```python
import clustplorer
from clustplorer.web import app
```

**Expected result**: No errors. If you see `ModuleNotFoundError`, go back and check that step 2
(`. .venv/bin/activate`) was run in the same terminal, and that all `uv pip install` commands completed
without errors.

---

## 3. Getting the Service IPs

Since k3s runs on the same machine you're developing on, you can connect directly to the k3s
internal ClusterIPs. No port-forwarding is needed.

Run this command to find the IPs of the three services:

```bash
kubectl get services -A | grep -E "postgresql|keycloak|openfga"
```

You should see output like this (your IPs **will be different**):

```
default        postgresql                 ClusterIP   10.43.236.45   <none>   5432/TCP          ...
keycloak       keycloak-http    ClusterIP   10.43.74.105   <none>   80/TCP            ...
openfga        openfga                    ClusterIP   10.43.202.22   <none>   8080/TCP,8081/TCP ...
```

Write down the three IPs from the `CLUSTER-IP` column. In the example above:
- **PostgreSQL**: `10.43.236.45`
- **Keycloak**: `10.43.74.105`
- **OpenFGA**: `10.43.202.22`

You will need these in step 5.

> **If the command returns nothing**: k3s is not running or the services are not deployed.
> Run `kubectl get pods -A` to check the cluster state.

---

## 4. Verifying Service Connectivity

Before configuring VSCode, verify that each service is reachable. Replace `<IP>` with the actual IPs
you wrote down in step 3.

**Test PostgreSQL:**
```bash
psql postgresql://postgres:password@<POSTGRES_IP>:5432/postgres -c "SELECT 1;"
```
Expected: prints `1`. If it hangs or says "connection refused", the PostgreSQL pod is not running.

**Test Keycloak:**
```bash
curl -s http://<KEYCLOAK_IP>:8080/auth/realms/visual-layer | python3 -m json.tool | head
```
Expected: prints JSON starting with `{"realm": "visual-layer", ...}`. If it says "connection refused",
the Keycloak pod is not running.

**Test OpenFGA:**
```bash
curl -s http://<OPENFGA_IP>:8080/healthz
```
Expected: prints `{"status":"SERVING"}`. If it says "connection refused", the OpenFGA pod is not running.

> **If any test fails**: Check the pod status with `kubectl get pods -A`. Look for pods that are
> not in `Running` state. Check their logs with `kubectl logs -n <namespace> <pod-name>`.

---

## 5. Getting Keycloak Admin Credentials

The Keycloak admin username and password are stored as a Kubernetes secret. Run these two commands to
retrieve them:

```bash
# Get the admin username
kubectl get secret keycloak-admin -n keycloak -o jsonpath='{.data.username}' | base64 -d
echo  # prints a newline so your prompt doesn't merge with the output

# Get the admin password
kubectl get secret keycloak-admin -n keycloak -o jsonpath='{.data.password}' | base64 -d
echo
```

Write down both values. You will need them in the next step.

> **If you get "not found"**: The Keycloak secret hasn't been created yet. Check that Keycloak was
> installed properly with `kubectl get secrets -n keycloak`.

---

## 6. Setting Up VSCode for Debugging

### 6.1 Create the launch configuration file

1. In the repo root, create the folder `.vscode` if it doesn't already exist:
   ```bash
   mkdir -p .vscode
   ```

2. Create the file `.vscode/launch.json` with the content below.

3. **Before saving**: replace **every** placeholder (the values in `<angle brackets>`) with the real
   values you collected in steps 3 and 5. There are 8 placeholders total — see the table after the
   JSON block.

```jsonc
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Clustplorer (K3s Debug)",
            "type": "debugpy",
            "request": "launch",
            "module": "uvicorn",
            "args": [
                "clustplorer.web:app",
                "--host", "0.0.0.0",
                "--port", "9999",
                "--log-level", "debug"
            ],
            "jinja": true,
            "justMyCode": false,
            "console": "integratedTerminal",
            "cwd": "${workspaceFolder}",
            "env": {
                // ── Connection strings (MUST CHANGE — see table below) ──
                "PG_URI": "postgresql://postgres:password@<POSTGRES_CLUSTER_IP>:5432/postgres",
                "OPENFGA_API_URL": "http://<OPENFGA_CLUSTER_IP>:8080",
                "OIDC_INTERNAL_BASE_URL": "http://<KEYCLOAK_CLUSTER_IP>:8080/auth",
                "OIDC_ISSUER": "http://<KEYCLOAK_CLUSTER_IP>:8080/auth/realms/visual-layer",
                "KEYCLOAK_ADMIN_USER": "<KEYCLOAK_ADMIN_USER>",
                "KEYCLOAK_ADMIN_PASSWORD": "<KEYCLOAK_ADMIN_PASSWORD>",
                "NO_PROXY": "localhost,127.0.0.1,<POSTGRES_CLUSTER_IP>,<KEYCLOAK_CLUSTER_IP>,<OPENFGA_CLUSTER_IP>",
                "no_proxy": "localhost,127.0.0.1,<POSTGRES_CLUSTER_IP>,<KEYCLOAK_CLUSTER_IP>,<OPENFGA_CLUSTER_IP>",

                // ── Auth & identity ──
                "DISABLE_AUTH": "true",
                "OIDC_CLIENT_ID": "visual-layer-app",
                "OIDC_CLIENT_SECRET": "CHANGE_ME_IN_PRODUCTION",
                "OIDC_REDIRECT_URI": "http://localhost:9999/api/v1/oidc/callback",
                "OIDC_VERIFY_CERTIFICATE": "false",
                "OPENFGA_STORE_NAME": "visual-layer",
                "OPENFGA_ALLOW_BOOTSTRAP": "true",

                // ── Runtime / environment ──
                "FASTDUP_PRODUCTION": "1",
                "PRODUCT_VERSION": "2.53.0",
                "RUN_MODE": "ONPREM",
                "RUNNING_ENV": "on-prem",
                "SENTRY_OPT_OUT": "1",

                // ── Display & pagination ──
                "CDN_FULLPATH": "http://onprem.visual-layer.link/image",
                "CLUSTER_ENTITIES_PAGE_SIZE": "100",
                "CLUSTERS_PAGE_SIZE": "100",
                "SERVE_ORIGINAL_IMAGE": "true",
                "SKIP_IMAGE_THUMBNAIL_GENERATION": "true",
                "USE_THUMBNAILS": "true",
                "USE_OBJECT_PREVIEWS": "true",
                "EXPLORATION_PAGINATION_ENABLED": "true",
                "OBJECT_SIZE_FILTER_ENABLED": "true",

                // ── Dataset features ──
                "DATASET_LIMIT_PER_USER": "100",
                "DATASET_CREATION_V2": "true",
                "DATASET_SNAPSHOTS_ENABLED": "true",
                "DATASET_SHARE_ENABLED": "false",
                "DELETE_DATASET_ENABLED": "true",
                "ADD_MEDIA_ENABLED": "true",
                "SAVED_VIEWS_SHARE_ENABLED": "false",

                // ── Search ──
                "SEARCH_SIMILAR_CLUSTERS_USE_VECTOR_DB": "true",
                "SEARCH_SIMILAR_SIMILARITY_THRESHOLD": "0.3",
                "SEARCH_BAR_V2_DISABLED": "true",
                "FLAT_SEARCH_RESPONSE_DISABLED": "true",
                "RIGHT_PANEL_TOGGLE_DISABLED": "true",

                // ── Flywheel & model training (Camtek) ──
                "FLYWHEEL_ENABLED": "true",
                "FLYWHEEL_PREPROCESS_ENABLED": "true",
                "FLYWHEEL_SHOW_PREVIOUS_ITERATIONS": "true",
                "SKIP_FLYWHEEL_VALIDATION": "true",
                "TRAIN_MODEL_ENABLED": "true",
                "MODELS_CATALOG_ENABLED": "true",
                "DATASETS_JOB_SETUP_RECIPE_FILTERS_ENABLED": "true",
                "MODEL_STORAGE_DIRECTORY": "/var/lib/visual-layer/models",
                "MODELS_SAVE_DIR": "/var/lib/visual-layer/models",
                "HOST_MODEL_RESULTS_PATH": "/home/ubuntu/ADC/ADC.Output",
                "MODEL_RESULTS_PATH": "/home/ubuntu/ADC/ADC.Output",
                "GROUND_TRUTH_DIR_PATH": "/ground-truths",
                "TRAINING_TASK_SNAPSHOT_DIR": "/var/tmp/",
                "DB_CSV_EXPORTS_DIR": "/db-csv-exports",
                "CAMTEK_TRAIN_API_ENDPOINT": "10.20.30.40:5000",

                // ── Datasets (local storage) ──
                // DATASETS_CREATION_DIRECTORY must be the pod-internal mount path (/datasets),
                // NOT the host path. The pipeline pod reads source_uri from the DB and checks
                // os.path.isdir() inside the pod — if this is the host path it won't match.
                "DATASETS_CREATION_DIRECTORY": "/datasets",
                // DATASETS_HOST_PATH is the host filesystem path to the same storage.
                // Used by the debug backend to access files for preview generation.
                "DATASETS_HOST_PATH": "/home/ubuntu/datasets",

                // ── Scan Results / Data Server gRPC ──
                "DATA_SERVER_GRPC_ENDPOINT": "<DATA_SERVER_GRPC_ENDPOINT>",

                // ── Pipeline ──
                "VL_ARGO_PIPELINE_ENABLED": "true",
                "VL_ARGO_PIPELINE_STRUCTURE": "single-step",
                "VL_K8S_NAMESPACE": "default",
                "VL_K8S_PIPELINE_IMAGE": "<VL_K8S_PIPELINE_IMAGE>",
                "VL_GPU_K8S_PIPELINE_IMAGE": "<VL_GPU_K8S_PIPELINE_IMAGE>",

                // ── DuckDB ──
                "DUCKDB_EXPLORATION_ENABLED": "true",
                "DUCKDB_EXPLORATION_VECTORS_ENABLED": "false",
                "DUCKDB_CLEANUP_ENABLED": "false",
                "DUCKDB_DATASETS_DIR": "/duckdb_datasets",
                "DUCKDB_TEMP_DIR": "/tmp/duckdb_datasets/tmp",
                "DUCKDB_THREADS": "8",
                "DUCKDB_MEMORY_LIMIT_GB": "4",

                // ── Disabled / not needed locally ──
                "SINGLE_ORG_WORKSPACE_ENABLED": "false",
                "USER_MANAGEMENT_ENABLED": "false"
            }
        }
    ]
}
```

### 6.2 Placeholder reference

Every `<...>` value in the JSON above **must** be replaced. Here is exactly where to get each one:

| Placeholder | What to run | Example value |
|---|---|---|
| `<POSTGRES_CLUSTER_IP>` | `kubectl get svc -n default postgresql -o jsonpath='{.spec.clusterIP}'` | `10.43.236.45` |
| `<KEYCLOAK_CLUSTER_IP>` | `kubectl get svc -n keycloak keycloak-http -o jsonpath='{.spec.clusterIP}'` | `10.43.74.105` |
| `<OPENFGA_CLUSTER_IP>` | `kubectl get svc -n openfga openfga -o jsonpath='{.spec.clusterIP}'` | `10.43.202.22` |
| `<KEYCLOAK_ADMIN_USER>` | `kubectl get secret keycloak-admin -n keycloak -o jsonpath='{.data.username}' \| base64 -d` | `admin` |
| `<KEYCLOAK_ADMIN_PASSWORD>` | `kubectl get secret keycloak-admin -n keycloak -o jsonpath='{.data.password}' \| base64 -d` | *(your password)* |
| `<DATA_SERVER_GRPC_ENDPOINT>` | Ask the Camtek team for the Data Server address | `10.5.1.126:5050` |
| `<VL_K8S_PIPELINE_IMAGE>` | `kubectl get configmap config -o jsonpath='{.data.VL_K8S_PIPELINE_IMAGE}'` | `visual-layer/pl-cpu:2.53.0` |
| `<VL_GPU_K8S_PIPELINE_IMAGE>` | `kubectl get configmap config -o jsonpath='{.data.VL_GPU_K8S_PIPELINE_IMAGE}'` | `visual-layer/pl-gpu:2.53.0` |

> **Double-check**: After replacing, search the file for `<` — if you find any remaining angle brackets
> inside a value string, you missed a placeholder.

### 6.3 How to run the debugger

1. Open VSCode in the repo root folder (`code .` from the terminal).
2. Make sure the Python interpreter is set to `.venv/bin/python` (bottom-left corner of VSCode, or
   `Ctrl+Shift+P` → "Python: Select Interpreter" → choose the `.venv` one).
3. Go to the **Run and Debug** panel (click the play icon with a bug on the left sidebar, or press `Ctrl+Shift+D`).
4. In the dropdown at the top, select **"Clustplorer (K3s Debug)"**.
5. Set breakpoints by clicking on the left margin of any `.py` file (a red dot appears).
6. Press **F5** to start debugging.

The backend will start on `http://localhost:9999`. You can open `http://localhost:9999/docs` in your
browser to see the API documentation and test endpoints.

> **After making code changes**: The launch config does not use `--reload` (auto-reload breaks the
> debugger). Press **Ctrl+Shift+F5** to restart the debug session, or stop it with **Shift+F5** and
> press **F5** again.

---

## 7. Troubleshooting

### The backend won't start — database connection error

1. Check that the PostgreSQL pod is running:
   ```bash
   kubectl get pods -n default | grep postgres
   ```
   The status should say `Running`. If it says `CrashLoopBackOff` or `Error`, check its logs:
   ```bash
   kubectl logs -n default <postgres-pod-name>
   ```

2. Verify the ClusterIP hasn't changed (it can change after a k3s restart):
   ```bash
   kubectl get svc -n default postgresql
   ```
   If the IP is different from what's in your `launch.json`, update it.

3. Test connectivity directly:
   ```bash
   psql postgresql://postgres:password@<POSTGRES_IP>:5432/postgres -c "SELECT 1;"
   ```

### Local folder datasets fail with "Folder not found" on the debug backend

The debug backend runs on the Ubuntu host, so `DATASETS_CREATION_DIRECTORY=/datasets` (the pod-internal
mount path) doesn't exist as a real directory. Create a symlink once per machine:

```bash
sudo ln -s /home/ubuntu/datasets /datasets
```

This makes the debug backend behave identically to the deployed backend, which has `/datasets` mounted
via PVC. Only needs to be done once — it survives reboots.

### The backend won't start — Keycloak health check fails

This happens when `DISABLE_AUTH` is set to `"false"` but Keycloak is not reachable.

**Quick fix**: Set `DISABLE_AUTH` to `"true"` in your `launch.json` to skip authentication entirely.

**To actually fix it**:
1. Check the Keycloak pod: `kubectl get pods -n keycloak`
2. Check the logs: `kubectl logs -n keycloak statefulset/keycloak-keycloakx`
3. Verify the Keycloak ClusterIP in your `launch.json` matches the current one.

### The backend won't start — OpenFGA errors

1. Make sure `OPENFGA_ALLOW_BOOTSTRAP` is set to `"true"` in your `launch.json`. This lets the
   backend create the OpenFGA store and authorization model automatically on first run.
2. Check the OpenFGA pod: `kubectl get pods -n openfga`
3. Check the logs: `kubectl logs -n openfga deployment/openfga`

### Creation, LP or any other task seems to be stuck
```bash
kubectl get pods
```
if you are seeing those tasks in pending it's one of the following:
1. There are other tasks which currently running and no free resources are left.
2. There isn't enough resources (cpu, memory) in the pool in the first place.

### Training service wasn't installed so you are getting an error when triggering it
1. Install the camtek training service if possible.
2. You can use an empty string in the CAMTEK_TRAIN_API_ENDPOINT and then it will run through the mock. 

### Post-reinstall checklist (after full wipe and redeploy)

After running the full reinstall sequence (helm uninstall → delete PVCs/PVs → helm upgrade → vl-admin install keycloak/openfga), **all ClusterIPs change**. You must do all of the following before the debug backend will work:

**1. Get the new ClusterIPs:**
```bash
echo "PostgreSQL: $(kubectl get svc postgresql -n default -o jsonpath='{.spec.clusterIP}')"
echo "Keycloak:   $(kubectl get svc keycloak-http -n keycloak -o jsonpath='{.spec.clusterIP}')"
echo "OpenFGA:    $(kubectl get svc openfga -n openfga -o jsonpath='{.spec.clusterIP}')"
echo "Keycloak password: $(kubectl get secret keycloak-admin -n keycloak -o jsonpath='{.data.password}' | base64 -d)"
```

**2. Update `.vscode/launch.json`** with the new IPs for these keys:
- `PG_URI` → new PostgreSQL IP
- `OPENFGA_API_URL` → new OpenFGA IP
- `OIDC_INTERNAL_BASE_URL` → new Keycloak IP
- `OIDC_ISSUER` → new Keycloak IP
- `KEYCLOAK_ADMIN_PASSWORD` → new password from step 1
- `NO_PROXY` / `no_proxy` → update all three IPs

**3. Fix the OpenFGA sync flag** (blocks all authenticated requests if false):
```bash
kubectl exec -n default postgresql-0 -- psql -U postgres -d postgres -c \
  "UPDATE runtime_settings SET value = 'true' WHERE key = 'openfga_access_sync_completed';"
```

**4. Create an admin user** for `http://onprem.visual-layer.link`:
```bash
# Get token
KEYCLOAK_URL="http://$(kubectl get svc keycloak-http -n keycloak -o jsonpath='{.spec.clusterIP}'):8080"
ADMIN_PASS=$(kubectl get secret keycloak-admin -n keycloak -o jsonpath='{.data.password}' | base64 -d)
TOKEN=$(curl -s -X POST "$KEYCLOAK_URL/auth/realms/master/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=$ADMIN_PASS&grant_type=password&client_id=admin-cli" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Create Keycloak user
curl -s -X POST "$KEYCLOAK_URL/auth/admin/realms/visual-layer/users" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin@camtek.com","email":"admin@camtek.com","firstName":"Admin","lastName":"Camtek","enabled":true,"credentials":[{"type":"password","value":"Admin123!","temporary":false}]}'

# Get the Keycloak user ID
KC_USER_ID=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "$KEYCLOAK_URL/auth/admin/realms/visual-layer/users?username=admin@camtek.com" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])")

# Create VL database user
kubectl exec -n default postgresql-0 -- psql -U postgres -d postgres -c \
  "INSERT INTO users (user_identity, identity_provider, email, name, username, dataset_quota)
   VALUES ('$KC_USER_ID', 'keycloak', 'admin@camtek.com', 'Admin Camtek', 'admin@camtek.com', 100)
   ON CONFLICT DO NOTHING;"
```

**5. Restart the debug backend** in VSCode (Shift+F5 then F5).

---

### ClusterIPs changed after a k3s restart

k3s may assign new ClusterIPs to services after a restart. If things suddenly stop working:

1. Re-run the command from step 3:
   ```bash
   kubectl get services -A | grep -E "postgresql|keycloak|openfga"
   ```
2. Compare the IPs with what's in your `.vscode/launch.json`.
3. Update any that changed.

### How to check the backend logs running inside k3s (for comparison)

```bash
kubectl logs -f deployment/clustplorer-deployment
```

This streams the logs from the deployed backend. Useful when comparing behavior between your local
debug session and the production deployment.

---

## 8. Running Tests

Tests are run through `./run_tests.sh`, which handles everything for you — it creates its own virtualenv
(`venv_tests`), spins up dedicated PostgreSQL (port 5555) and OpenFGA (port 8080) containers in Docker,
creates the DB schema, runs the tests, and tears everything down when done.

**Do not run pytest directly** — the script manages the test infrastructure and environment.

Always redirect output to a file since there's a lot of it:

```bash
# Run all tests
./run_tests.sh > /tmp/test_output.log 2>&1

# Run a specific test by name
./run_tests.sh -k test_name_pattern > /tmp/test_output.log 2>&1

# Stop on first failure (useful when debugging)
./run_tests.sh -x > /tmp/test_output.log 2>&1

# Skip reinstalling requirements (faster on repeat runs)
./run_tests.sh -f > /tmp/test_output.log 2>&1

# Run tests in parallel with 4 workers
./run_tests.sh -w 4 > /tmp/test_output.log 2>&1

# Run a specific test group (used in CI — e.g., group 2 of 4)
./run_tests.sh -G 2/4 > /tmp/test_output.log 2>&1
```

### Finding errors in the output

After the tests finish, grep the log file:

```bash
# Show failed tests
grep -E "FAILED|ERROR|ERRORS" /tmp/test_output.log

# Show tracebacks leading to failures
grep -B 5 "FAILED\|AssertionError\|Exception" /tmp/test_output.log

# Show the pytest summary section
grep -A 20 "short test summary" /tmp/test_output.log
```
### Switch creation between CPU\GPU
Assuming you are using the new models.zip. 
In order to switch between CPU and GPU creation you need to update 1 feature flag and run the helm command again.
follow these steps:
1. Go to devops/env/k3s/values.yaml
2. Find the flywheelPreprocessEnabled field and look at the value (true -will use GPU for creation, false -CPU)
3. Change the value according to what you need\want.
4. save the file.
5. run the helm command (from the root of the code) helm upgrade -i visual-layer devops/visual-layer -f devops/env/k3s/values.yaml -f devops/clients/camtek/values.yaml --namespace default
 

### Prerequisites

The script needs Docker to run the test containers. Make sure `docker ps` works without sudo.
If it doesn't, add your user to the docker group: `sudo usermod -aG docker $USER` (then log out and back in).