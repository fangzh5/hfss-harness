"""Content-based execution identity. A path alone is never model identity."""

import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def context_digest(context):
    data = json.dumps(context, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def valid_manifest(manifest):
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        return False
    try:
        context = manifest["context"]
        return (manifest.get("verified") is True
                and isinstance(context.get("source_sha256"), str)
                and len(context["source_sha256"]) == 64
                and bool(context.get("solver_version"))
                and manifest["fingerprint"] == context_digest(context))
    except (KeyError, TypeError, ValueError):
        return False


def build_execution_manifest(config, adapter):
    """Capture the copied model and actual fixed/dependent variables before search.

    Solver settings and materials contained in AEDT are covered by its byte hash;
    runtime simulator overrides and acquisition settings are covered separately.
    Unverified adapters may run offline, but cannot supply reusable HFSS history.
    """
    simulator = dict(config.get("simulator") or {})
    hfss = dict(simulator.pop("hfss", {}) or {})
    for name in ("project_path", "non_graphical", "new_desktop", "close_on_exit",
                 "remove_lock", "aedt_process_id", "use_grpc_api"):
        hfss.pop(name, None)
    parameters = [{"name": item["name"], "unit": item.get("unit", "mm")}
                  for item in config.get("parameters", [])]
    excluded = {item["name"] for item in parameters}
    excluded.update((getattr(adapter, "config", {}).get("fixed_parameters") or {}).keys())
    capture = getattr(adapter, "capture_current_parameter_state", None)
    baseline = capture() if callable(capture) else None
    app = getattr(adapter, "app", None)
    solver_version = getattr(app, "aedt_version_id", None)
    try:
        pyaedt_version = version("pyaedt")
    except PackageNotFoundError:
        pyaedt_version = None
    source_hash = getattr(adapter, "source_project_sha256", None)
    context = {"source_sha256": source_hash, "solver_version": solver_version,
               "pyaedt_version": pyaedt_version, "simulator": simulator, "hfss": hfss,
               "parameters": parameters, "baseline_expressions": (
                   {name: str(value) for name, value in baseline.items() if name not in excluded}
                   if baseline is not None else None),
               "fixed_parameters": dict(getattr(adapter, "config", {}).get("fixed_parameters") or {}),
               "actual_design": getattr(app, "design_name", None),
               "metric_acquisition": {name: config.get("target", {}).get(name) for name in
                                      ("far_field", "boresight")},
               "geometry_metric": config.get("target", {}).get("fitness", {}).get("geometry_metric"),
               "result_contract_version": 1}
    manifest = {"schema_version": 1, "context": context, "fingerprint": context_digest(context),
                "verified": bool(source_hash and solver_version and baseline is not None
                                 and context["actual_design"])}
    return manifest
