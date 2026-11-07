"""FastAPI app. Dev: python -m ap_automation serve --reload  (docs at http://127.0.0.1:8000/docs)

If frontend/dist exists (npm run build), it is served at / so one process runs the whole app.
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..common import REPO_ROOT
from . import store
from .routers import ai, datasets, exceptions, intake, invoices

app = FastAPI(title="AP Automation API", version=__version__,
              description="Invoice intake, extraction, three-way match, exception routing, approval and payment "
                          "readiness over synthetic procure-to-pay data.")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health", tags=["meta"])
def health():
    from ..llm import status
    return {"status": "ok", "version": __version__, "datasets": store.list_datasets(), "llm": status()}


for r in (datasets.router, invoices.router, exceptions.router, intake.router, ai.router):
    app.include_router(r, prefix="/api")

DIST = REPO_ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path == "api" or path.startswith("api/"):     # unknown API routes stay JSON 404s
            raise HTTPException(404, "Not Found")
        return FileResponse(DIST / "index.html")
