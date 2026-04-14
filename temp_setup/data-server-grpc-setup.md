# Data Server gRPC — Setup Guide

## What is the Data Server?

The Camtek Data Server is a .NET service running on the Camtek machine. It exposes scan results, wafer repositories, and inspection data over gRPC (default port **5050**).

VL connects to it to power the **Scan Results** page: listing repositories, filtering wafers, selecting scan results for export, and triggering ADC export.

**Mock mode**: When `DATA_SERVER_GRPC_ENDPOINT` is not configured, VL automatically falls back to a mock client (`DataServerClientMock`) that returns empty/stub data. The UI works but shows no real scan results.

---

## Prerequisites

Before configuring VL, ensure the following are true from the Ubuntu machine:

1. **The Camtek Data Server is running** on the Camtek machine.

2. **gRPC reflection is enabled** on the server — VL uses runtime reflection to discover the API. No manual `.proto` compilation is needed, but the server must have reflection enabled (it does by default on the Camtek setup).

3. **Port 5050 is reachable** from the Ubuntu machine:
   ```bash
   nc -zv <camtek-machine-ip> 5050
   # Expected: Connection to <ip> 5050 port [tcp/*] succeeded!
   ```

4. **The CIFS share is mounted** (see [Datasets / export path setup](#datasets--export-path-setup) below).

---

## Configuration

### For local debug (VSCode backend)

In `.vscode/launch.json`, inside the **"Clustplorer (K3s Debug)"** configuration's `env` block:

```json
"DATA_SERVER_GRPC_ENDPOINT": "10.5.1.126:5050",
"DATASETS_HOST_PATH": "/home/ubuntu/datasets",
"DATASETS_CREATION_DIRECTORY": "/datasets"
```

Replace `10.5.1.126` with the actual IP of the Camtek machine running the Data Server.

### For k3s deployment

In `devops/clients/camtek/values.yaml`:

```yaml
dataServer:
  grpcEndpoint: "10.5.1.126:5050"
```

Then redeploy:
```bash
helm upgrade visual-layer ./devops/visual-layer \
  -f devops/visual-layer/values.yaml \
  -f devops/clients/camtek/values.yaml \
  -n default
```

---

## Datasets / export path setup

### Why this is needed

When the user clicks **Export** in the UI:

1. VL calls `DataServerClient.export_adc()` — this tells the **Camtek .NET service** to write the selected scan result images to `export_path` (a Windows-style path, e.g. `D:\ExportVl` or `\\<nas>\share\ExportVl`).
2. The Camtek service writes the files to that Windows path on its machine.
3. VL then needs to **read those files from Ubuntu** to copy them into `/home/ubuntu/datasets/` so the image-proxy k8s pod can serve them.

Step 3 is the problem: the Camtek service writes to a Windows path, but VL runs on Ubuntu. **A CIFS mount is the bridge** — Ubuntu mounts the same location the Camtek service writes to, so the files become visible on the Ubuntu filesystem.

> If the Data Server is configured to write to a path that is already directly accessible on Ubuntu (e.g., the same machine or a Linux share), no CIFS mount is needed.

### Required directory layout

The mounted path must sit under `DATASETS_HOST_PATH`, in a subfolder whose name matches the last path component of `export_path`:

```
/home/ubuntu/datasets/         ← DATASETS_HOST_PATH
└── ExportVl/                  ← mounted or local folder (= last part of export_path)
    └── MTK-<scan-id>/         ← written by the Camtek Data Server on export
        ├── images/
        └── ...
```

So if `export_path` is `D:\ExportVl` or `\\nas\share\ExportVl`, the folder name is `ExportVl` and it must appear at `/home/ubuntu/datasets/ExportVl/`.

### Mounting the CIFS share

```bash
sudo mkdir -p /home/ubuntu/datasets/ExportVl
sudo mount -t cifs //<camtek-machine-or-nas-ip>/<share-name> /home/ubuntu/datasets/ExportVl \
  -o username=<user>,password=<pass>,uid=ubuntu,gid=ubuntu
```

To make it permanent, add to `/etc/fstab`:
```
//<camtek-machine-or-nas-ip>/<share-name>  /home/ubuntu/datasets/ExportVl  cifs  username=<user>,password=<pass>,uid=ubuntu,gid=ubuntu,_netdev  0  0
```

There also needs to be a symlink from `/datasets` → `/home/ubuntu/datasets` so the k8s pod (which sees `/datasets` via the PVC hostPath) finds the same files:
```bash
sudo ln -s /home/ubuntu/datasets /datasets
```

---

## How the gRPC client works

- **No static `.proto` files** — `ReflectionFactory` connects to the server at startup and uses gRPC server reflection to discover all services and message types at runtime. This means updates to the Camtek API schema require no changes on the VL side.

- **Lazy initialization** — the gRPC channel is created on first use and reused for the lifetime of the process.

- **100 MB message limit** — configured on the channel to handle large scan result payloads.

- **Known limitation**: the first call after backend start is slow (~20 seconds) because `ReflectionFactory` fetches and registers all proto descriptors. Subsequent calls are fast.

---

## Verify it's working

After configuring the endpoint and restarting the backend, open the Scan Results page in the UI. You should see:

- Repository list populated (not empty)
- Wafer scan results loading when you select a repository

If you see empty lists, check the backend logs for gRPC errors:
```bash
# k3s pod logs
kubectl logs -n default deployment/visual-layer-clustplorer --tail=100 | grep -i "grpc\|data.server\|reflection"

# or in VSCode debug console — look for ReflectionFactory log lines
```

Common errors:
| Error | Cause | Fix |
|---|---|---|
| `StatusCode.UNAVAILABLE` | Can't reach `<ip>:5050` | Check firewall, verify `nc -zv <ip> 5050` |
| `StatusCode.UNIMPLEMENTED` | Reflection not enabled on server | Enable gRPC reflection on the .NET service |
| Empty repositories list | Connected but export path CIFS not mounted | Check CIFS mount and `DATASETS_HOST_PATH` |
| `Export source not found` | CIFS not mounted or export path wrong | Verify the mount and that the server wrote to the expected path |
