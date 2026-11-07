"""REST API contract tests against a freshly built starter dataset."""
import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from ap_automation.__main__ import build_all  # noqa: E402
from ap_automation.api import store  # noqa: E402
from ap_automation.common import load_config  # noqa: E402

CFG = load_config()


@pytest.fixture(scope="module")
def client(tmp_path_factory, monkeypatch_module):
    root = tmp_path_factory.mktemp("data")
    build_all(root / "starter", CFG, 0.1, CFG["seed"])
    monkeypatch_module.setattr(store, "DATA_ROOT", root)
    from ap_automation.api.main import app
    return TestClient(app)


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


def test_health_and_datasets(client):
    assert client.get("/api/health").json()["status"] == "ok"
    assert [d["name"] for d in client.get("/api/datasets").json()] == ["starter"]


def test_summary_matches_policy(client):
    s = client.get("/api/datasets/starter/summary").json()
    assert s["validation"]["status"] == "PASS"
    assert {a["status"] for a in s["acceptance"]} == {"PASS"}
    assert s["kpis"]["payment_ready"] + s["kpis"]["on_hold"] == 200


def test_invoice_list_filters_and_detail(client):
    held = client.get("/api/datasets/starter/invoices", params={"status": "ON_HOLD", "limit": 500}).json()
    assert held["total"] == 60 and all(r["final_status"] == "ON_HOLD" for r in held["items"])
    d = client.get(f"/api/datasets/starter/invoices/{held['items'][0]['invoice_id']}").json()
    assert d["exceptions"] and d["payment"] is None and not d["approvals"]
    assert d["events"][-1]["to_state"] == "ON_HOLD"
    assert client.get("/api/datasets/starter/invoices/INV-NOPE-2026-000001").status_code == 404


def test_exception_queues(client):
    e = client.get("/api/datasets/starter/exceptions").json()
    assert sum(e["queues"].values()) == e["total"] == 60


def test_intake_extract_round_trip(client):
    inv = client.get("/api/datasets/starter/invoices", params={"status": "PAYMENT_READY", "limit": 1}).json()
    doc = client.get(f"/api/datasets/starter/invoices/{inv['items'][0]['invoice_id']}").json()["document"]["text"]
    r = client.post("/api/datasets/starter/intake/extract", json={"text": doc}).json()
    assert all(c["ok"] for c in r["checks"])


def test_rejects_unknown_or_unsafe_dataset_names(client):
    assert client.get("/api/datasets/../secret/summary").status_code == 404
    assert client.get("/api/datasets/nope/summary").status_code == 404
    assert client.post("/api/datasets/nope/run").status_code == 400
