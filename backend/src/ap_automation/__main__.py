"""CLI.  python -m ap_automation run-all --preset starter

Stages: generate -> process -> export -> validate -> evaluate -> report (+ manifest).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .common import DATA_ROOT, REPO_ROOT, load_config, write_json
from .docs import write_data_dictionary
from .evaluation import evaluate
from .export import export, reproducibility, write_manifest
from .generator import generate_dataset
from .llm import Claude
from .llm import status as llm_status
from .pipeline.workflow import run_pipeline
from .report import build_report
from .validation import validate


def _llm():
    """Claude client, or exit with a clear message when it is not configured."""
    st = llm_status()
    if not st["available"]:
        sys.exit(f"LLM not configured: {st['hint']}")
    return Claude()


def _plan(data: Path) -> dict:
    return json.loads((data / "reports" / "generation_plan.json").read_text(encoding="utf-8"))


def build_all(out: Path, cfg: dict, scale: float, seed: int, log=lambda *a: None, llm=None) -> dict:
    log(f"[1/6] generate  scale={scale} seed={seed} -> {out}")
    plan = generate_dataset(out, cfg, scale, seed)
    log(f"      volumes {plan['volumes']}")
    log("[2/6] process   intake -> extraction -> match -> route -> approve -> pay")
    log(f"      {run_pipeline(out, cfg, llm)}")
    log("[3/6] export    CSV + JSON + SQL seed + SQLite")
    export(out)
    log("[4/6] validate")
    v = validate(out, cfg, scale)
    log(f"      {v['status']}: {v['checks_run']} checks, {v['checks_failed']} failed")
    log("[5/6] evaluate")
    e = evaluate(out, cfg)
    for a in e["acceptance_criteria"]:
        log(f"      {a['status']}  {a['criterion']}  ({a['evidence']})")
    log("[6/6] report")
    log(f"      {build_report(out)}")
    return {"validation": v["status"], "acceptance": [a["status"] for a in e["acceptance_criteria"]]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ap_automation", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=None, help="config JSON (default configs/default.json)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def scaled(p):
        p.add_argument("--preset", choices=["starter", "full"], default="starter")
        p.add_argument("--scale", type=float, help="override preset scale (1.0 = 2,000 invoices)")
        p.add_argument("--seed", type=int, help="override config seed")
        p.add_argument("--out", type=Path, help="output dataset dir (default data/<preset>)")

    for name in ("run-all", "generate", "reproduce"):
        p = sub.add_parser(name)
        scaled(p)
        if name == "run-all":
            p.add_argument("--llm", action="store_true", help="Claude fallback for documents the rules cannot read")
    for name in ("process", "export", "validate", "evaluate", "report", "llm-benchmark"):
        p = sub.add_parser(name)
        p.add_argument("--data", type=Path, required=True, help="dataset dir, e.g. data/starter")
        if name == "process":
            p.add_argument("--llm", action="store_true", help="Claude fallback for unreadable documents")
        if name == "llm-benchmark":
            p.add_argument("--n", type=int, default=None, help="documents to test (default from config)")
    sub.add_parser("llm-status", help="show whether the Claude integration is configured")
    sub.add_parser("docs", help="regenerate docs/data_dictionary.md from schema.py")
    sp = sub.add_parser("serve", help="start the REST API (FastAPI) on http://127.0.0.1:8000")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8000)
    sp.add_argument("--reload", action="store_true")
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    log = lambda *m: print(*m, flush=True)

    if a.cmd in ("run-all", "generate", "reproduce"):
        scale = a.scale if a.scale is not None else cfg["scale_presets"][a.preset]
        seed = a.seed if a.seed is not None else cfg["seed"]
        out = a.out or DATA_ROOT / (a.preset if a.scale is None else f"scale_{scale:g}")
        command = " ".join(["python -m ap_automation"] + (argv if argv is not None else sys.argv[1:]))
        if a.cmd == "generate":
            log(generate_dataset(out, cfg, scale, seed))
        elif a.cmd == "run-all":
            res = build_all(out, cfg, scale, seed, log, _llm() if a.llm else None)
            write_manifest(out, seed, scale, command)
            log(f"done: validation {res['validation']}, acceptance {res['acceptance'].count('PASS')}/"
                f"{len(res['acceptance'])} -> {out / 'reports' / 'report.html'}")
            return 0 if res["validation"] == "PASS" and set(res["acceptance"]) == {"PASS"} else 1
        else:
            res = reproducibility(cfg, scale, seed, out, build_all)
            write_json(out / "reports" / "reproducibility.json", res)
            log(f"identical across 2 regenerations: {res['identical']} ({res['files_compared']} files); "
                f"matches committed dataset: {res.get('matches_committed_dataset')}")
            return 0 if res["identical"] else 1
    elif a.cmd == "process":
        log(run_pipeline(a.data, cfg, _llm() if a.llm else None))
    elif a.cmd == "llm-status":
        log(json.dumps(llm_status(), indent=1))
    elif a.cmd == "llm-benchmark":
        from .llm.benchmark import run_benchmark
        r = run_benchmark(a.data, a.n or cfg["llm"]["benchmark_documents"], _llm())
        log(json.dumps({k: r[k] for k in ("documents", "model", "document_exact_match", "tokens", "errors")}, indent=1))
    elif a.cmd == "export":
        log(export(a.data))
    elif a.cmd == "validate":
        v = validate(a.data, cfg, _plan(a.data)["scale"])
        log(f"{v['status']}: {v['checks_run']} checks, {v['checks_failed']} failed")
        return 0 if v["status"] == "PASS" else 1
    elif a.cmd == "evaluate":
        for c in evaluate(a.data, cfg)["acceptance_criteria"]:
            log(f"{c['status']}  {c['criterion']}  ({c['evidence']})")
    elif a.cmd == "report":
        log(build_report(a.data))
    elif a.cmd == "docs":
        write_data_dictionary()
        log(REPO_ROOT / "docs" / "data_dictionary.md")
    elif a.cmd == "serve":
        import uvicorn   # optional dependency: pip install -e ".[api]"
        uvicorn.run("ap_automation.api.main:app", host=a.host, port=a.port, reload=a.reload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
