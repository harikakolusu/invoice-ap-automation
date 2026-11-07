"""AI endpoints (Claude): integration status and the exception copilot."""
import threading

from fastapi import APIRouter, HTTPException

from ...llm import Claude, LLMError, LLMUnavailable, status
from ...llm.copilot import explain
from .. import store
from .invoices import invoice_detail

router = APIRouter(tags=["ai"])
_llm, _lock = None, threading.Lock()
_cache: dict[tuple, dict] = {}       # one Claude call per invoice per dataset version


def get_llm() -> Claude:
    """Shared client; 503 with a setup hint when the integration is not configured."""
    global _llm
    st = status()
    if not st["available"]:
        raise HTTPException(503, f"LLM not configured: {st['hint']}")
    with _lock:
        if _llm is None:
            _llm = Claude()
        return _llm


def call_llm(fn, *args):
    try:
        return fn(*args, get_llm())
    except LLMUnavailable as e:
        raise HTTPException(503, str(e)) from e
    except LLMError as e:
        raise HTTPException(502, str(e)) from e


@router.get("/llm/status")
def llm_status():
    return status()


@router.post("/datasets/{name}/invoices/{invoice_id}/copilot")
def copilot(name: str, invoice_id: str):
    """Claude explains why the invoice is held and drafts the follow-up. Advisory only."""
    ds = store.get(name)
    detail = invoice_detail(name, invoice_id)
    key = (name, invoice_id, id(ds))
    if key not in _cache:
        _cache[key] = call_llm(explain, detail)
    return _cache[key]
