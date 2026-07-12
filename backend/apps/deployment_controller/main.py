"""Composition root for the privileged deployment-controller process."""

from __future__ import annotations

import os
from collections.abc import Mapping

from rag.deployment.adapters.docker_compose import DockerComposeConfig, DockerComposeRuntime
from rag.deployment.http_api import DeploymentControllerServer
from rag.deployment.service import DeploymentService
from rag.deployment.validation import DEFAULT_SERVICES


def build_server(environment: Mapping[str, str] | None = None) -> DeploymentControllerServer:
    process_environment = os.environ if environment is None else environment
    token = process_environment.get("DEPLOYMENT_CONTROLLER_TOKEN", "").strip()
    if not token:
        raise RuntimeError("DEPLOYMENT_CONTROLLER_TOKEN must be configured.")
    allowed_services = {
        service.strip()
        for service in process_environment.get(
            "DEPLOYMENT_ALLOWED_SERVICES",
            ",".join(DEFAULT_SERVICES),
        ).split(",")
        if service.strip()
    }
    if not allowed_services:
        raise RuntimeError(
            "DEPLOYMENT_ALLOWED_SERVICES must include at least one service."
        )
    runtime = DockerComposeRuntime(
        DockerComposeConfig.from_environment(process_environment),
        environment=process_environment,
    )
    application = DeploymentService(runtime)
    return DeploymentControllerServer(
        ("0.0.0.0", int(process_environment.get("PORT", "8080"))),
        application=application,
        token=token,
        allowed_services=allowed_services,
    )


def main() -> None:
    server = build_server()
    print(f"deployment-controller listening on :{server.server_port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
