"""Dataset-level endpoints: list, dashboard summary, validation report, re-run the pipeline."""
from fastapi import APIRouter, HTTPException

from ...__main__ import build_all
from ...common import DATA_ROOT, load_config
from ...export import write_manifest
from .. import store

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.get("")
def datasets():
    out = []
    for name in store.list_datasets():
        ds = store.get(name)
        out.append({"name": name, "invoices": ds.plan["volumes"]["invoices"], "seed": ds.plan["seed"],
                    "scale": ds.plan["scale"], "validation": ds.validation["status"]})
    return out


@router.get("/{name}/summary")
def summary(name: str):
    ds = store.get(name)
    m = ds.metrics
    return {"dataset": name, "plan": ds.plan, "kpis": m["kpis"], "acceptance": m["acceptance_criteria"],
            "extraction": m["extraction"], "decisions": m["decisions"], "duplicates": m["duplicates"],
            "payment_safety": m["payment_safety"],
            "validation": {k: ds.validation[k] for k in ("status", "checks_run", "checks_failed")}}


@router.get("/{name}/validation")
def validation(name: str):
    return store.get(name).validation


@router.post("/{name}/run")
def run(name: str):
    """Regenerate + reprocess a preset dataset (starter ~4 s, full ~20 s)."""
    cfg = load_config()
    if name not in cfg["scale_presets"]:
        raise HTTPException(400, f"only presets can be re-run: {list(cfg['scale_presets'])}")
    if not store.run_lock.acquire(blocking=False):
        raise HTTPException(409, "a run is already in progress")
    try:
        scale = cfg["scale_presets"][name]
        res = build_all(DATA_ROOT / name, cfg, scale, cfg["seed"])
        write_manifest(DATA_ROOT / name, cfg["seed"], scale, f"POST /api/datasets/{name}/run")
        return res
    finally:
        store.run_lock.release()
