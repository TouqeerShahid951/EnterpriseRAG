# Deployment control capability

This package owns the authenticated workflow for applying vLLM container launch
limits. It is a request-driven control-plane capability, not a Celery worker or
a periodic background service.

- `application.py`, `controller_client.py`, and `dependencies.py` coordinate the
  public admin API with the internal controller.
- `validation.py`, `models.py`, `service.py`, and `ports.py` define the
  controller-side rules and application boundary.
- `adapters/docker_compose.py` is the only module that executes Docker commands.
- `http_api.py` owns the controller's internal HTTP contract.
- `apps/deployment_controller/main.py` only reads process configuration, wires
  dependencies, and starts the HTTP server.

Apply operations are serialized within the controller process. A retry is a
no-op when every selected running container already has the requested managed
launch arguments. A successful Compose command means the containers were
recreated or already matched; model readiness may remain `starting` while
weights load.

The controller intentionally runs in a dedicated minimal image. It still has
high privilege because local Compose orchestration requires the Docker socket,
so it must remain internal-only, use its dedicated token, and expose only the
allowlisted vLLM operation.

## Dashboard resource telemetry

`GET /api/v1/admin/system-resources` requires Platform Admin access and returns
the latest in-memory sample of CPU, available memory, and root-filesystem usage without Docker
socket access or new dependencies. CPU/memory are Linux host-visible counters:
inside Docker Desktop they describe the VM, not the physical machine or an
individual container's limit. Disk reports the API root filesystem's shared
capacity. Each failed/unsupported metric is explicitly unavailable; other
metrics remain usable. NVIDIA GPU telemetry is collected with a bounded, read-only `nvidia-smi` call.
Individual worker/container telemetry is not collected. One background sampler per
API process collects serially, with a two-second pause between samples. Dashboard
requests only read the shared snapshot: they do not read OS counters, sleep, or
launch GPU subprocesses. CPU averages the interval between samples; the first
CPU reading is unavailable until its second sample. Sampling runs on a dedicated
thread, started and stopped by API lifespan, outside HTTP request workers and the
event loop. Slow readings never spawn overlapping samplers or catch-up work.

The dashboard polls every two seconds while visible, pauses in hidden tabs,
refreshes on return, and backs off to ten seconds after errors. It reports the
actual sample timestamp. This is near-real-time polling, not continuous streaming.
Cold or older-than-ten-second snapshots return 503 with `Retry-After` and
`Cache-Control: no-store`; the UI retains its last sample with a delayed-update
warning. Failed collection is logged, retried on the next cycle, and does not
renew the old timestamp. Sampling cost scales with API processes, not viewers;
authentication and small HTTP responses still have a per-viewer cost.

Audit activity uses the authorized audit scope and a
7/30-day window; distinct actors are not claimed to be active logged-in users.

### Optional NVIDIA GPU monitoring

The resource endpoint includes device name, utilization, VRAM bytes, temperature,
and power for GPUs visible to the API container. Unsupported individual counters
are null, never zero. Missing tools, driver failures, and timeouts produce an
explicit GPU unavailable state without losing CPU, memory, or disk readings.
These are whole-device readings, not this application's share or remote model-server metrics.

Mac Docker does not expose the Apple GPU; the dashboard explains this limitation.
For Windows, use Docker Desktop's WSL2 backend with a supported NVIDIA GPU and
current Windows NVIDIA driver. Enable the optional override when starting the stack:

```sh
docker compose -f docker-compose.yml -f deploy/docker-compose.gpu-metrics.yml up -d
```

Keep including the override in subsequent Compose commands. It grants GPU access
to API replicas and exposes the NVIDIA utility; it does not install CUDA Python
packages or change inference to GPU. The existing reranker GPU override can be
combined with it when GPU inference is separately configured.

See [Docker Desktop GPU support](https://docs.docker.com/desktop/features/gpu/)
and [NVIDIA driver capabilities](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/docker-specialized.html).
