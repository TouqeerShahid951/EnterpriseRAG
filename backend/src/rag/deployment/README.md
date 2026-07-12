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
