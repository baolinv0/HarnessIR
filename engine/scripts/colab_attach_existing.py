"""Bind an existing authenticated Colab assignment without allocating a VM."""
import argparse
import json
import logging
import sys

import requests

import colab_client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--name", default="harnessir_existing_t4")
    parser.add_argument("--allow-busy-kernel-for-file-transfer", action="store_true")
    args = parser.parse_args()
    if not args.name.replace("_", "").replace("-", "").isalnum():
        raise ValueError("Local session name must be a simple identifier")
    colab_client.configure()
    from colab_cli import common
    from colab_cli.state import SessionState
    common.setup_logging(False)
    common.state.config_path = str(colab_client.PRIVATE / "sessions.json")
    old = common.state.store.get(args.name)
    if old is not None and old.endpoint != args.endpoint:
        raise ValueError("Local session name is already bound to another assignment")
    assignments = [a for a in common.state.client.list_assignments() if a.endpoint == args.endpoint]
    if len(assignments) != 1:
        raise ValueError("Exactly one matching existing Colab assignment is required")
    assignment = assignments[0]
    proxy = assignment.runtime_proxy_info
    if not proxy.token or not proxy.url:
        raise ValueError("Existing assignment has no usable runtime proxy")
    response = requests.get(
        proxy.url.rstrip("/") + "/api/kernels",
        params={"authuser": "0", "colab-runtime-proxy-token": proxy.token},
        headers={"X-Colab-Runtime-Proxy-Token": proxy.token}, timeout=(15, 30),
    )
    response.raise_for_status()
    kernels = response.json()
    if not isinstance(kernels, list) or len(kernels) != 1 or not kernels[0].get("id"):
        raise ValueError("Exactly one existing notebook kernel is required; no new kernel will be created")
    if kernels[0].get("execution_state") == "busy" and not args.allow_busy_kernel_for_file_transfer:
        raise ValueError("Existing notebook kernel is busy; preserve its active work")
    state = SessionState(
        name=args.name, endpoint=assignment.endpoint,
        token=proxy.token, url=proxy.url, token_expires_at=proxy.expires_at(),
        variant=assignment.variant.name, accelerator=assignment.accelerator.value,
        machine_shape=assignment.machine_shape.name if assignment.machine_shape else "STANDARD",
        kernel_id=kernels[0]["id"], session_id=None,
    )
    # Reuse the verified kernel; an unset ID would create a new kernel.
    common.state.store.add(state)
    print(json.dumps({"status": "existing_assignment_bound", "name": state.name,
                      "hardware_assignment": state.accelerator,
                      "new_runtime_created": False, "kernel_restarted": False,
                      "existing_kernel_verified": True,
                      "kernel_state": kernels[0].get("execution_state"),
                      "file_transfer_only_if_busy": args.allow_busy_kernel_for_file_transfer}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        logging.warning("Existing assignment binding failed: %s", type(error).__name__)
        print(json.dumps({"status": "binding_failed", "error_type": type(error).__name__,
                          "new_runtime_created": False,
                          "validation_fields": [list(e["loc"]) for e in error.errors(include_input=False)] if hasattr(error, "errors") else []}), file=sys.stderr)
        raise SystemExit(2)
