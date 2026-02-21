from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from apscheduler.schedulers.background import BackgroundScheduler
from database import engine, SessionLocal
import models
import os

# Create all tables on startup
models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="STOK — Agentic Inventory Manager",
    version="1.0.0",
    docs_url="/docs",   # keep docs accessible on Render for debugging
    redoc_url=None,
)

# CORS — allow all origins (Render URL changes on free tier)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────
from routers.auth import router as auth_router
from routers.upload import router as upload_router
from routers.actions import router as actions_router
from routers.data import (
    inventory_router, suppliers_router, audit_router,
    forecast_router, stats_router, agent_router
)

app.include_router(auth_router)
app.include_router(upload_router)
app.include_router(actions_router)
app.include_router(inventory_router)
app.include_router(suppliers_router)
app.include_router(audit_router)
app.include_router(forecast_router)
app.include_router(stats_router)
app.include_router(agent_router)

# ── Serve Frontend ────────────────────────────────────────────────
frontend_dir = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "frontend")
)

if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @app.get("/", include_in_schema=False)
    def serve_index():
        return FileResponse(os.path.join(frontend_dir, "index.html"))

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str):
        api_prefixes = (
            "auth/", "actions/", "inventory/", "suppliers/",
            "audit/", "upload/", "forecast/", "stats/",
            "agent/", "health", "docs", "openapi"
        )
        if full_path.startswith(api_prefixes):
            from fastapi import HTTPException
            raise HTTPException(404)
        return FileResponse(os.path.join(frontend_dir, "index.html"))


# ── Health (Render uses this to check service is alive) ───────────
@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}


# ── Background Scheduler ──────────────────────────────────────────
def run_agent_job():
    from services.agent import run_agent
    db = SessionLocal()
    try:
        count = run_agent(db)
        print(f"[Agent] Scan complete — {count} new actions created")
    except Exception as e:
        print(f"[Agent] Error: {e}")
    finally:
        db.close()


def keep_alive_ping():
    """Pings /health every 10min to prevent Render free tier sleep"""
    import urllib.request
    app_url = os.getenv("RENDER_EXTERNAL_URL", "")
    if app_url:
        try:
            urllib.request.urlopen(f"{app_url}/health", timeout=10)
            print("[KeepAlive] Pinged successfully")
        except Exception as e:
            print(f"[KeepAlive] Ping failed: {e}")


scheduler = BackgroundScheduler(timezone="UTC")
scheduler.add_job(run_agent_job, "interval", hours=1, id="agent_scan")
scheduler.add_job(keep_alive_ping, "interval", minutes=10, id="keep_alive")
scheduler.start()


@app.on_event("startup")
def startup():
    render_url = os.getenv("RENDER_EXTERNAL_URL", "not set")
    print(f"STOK started on Render — URL: {render_url}")


@app.on_event("shutdown")
def shutdown():
    scheduler.shutdown(wait=False)
