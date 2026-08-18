import os

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import SessionLocal, ensure_employee_credentials, init_db
from nest_employee_sync import sync_nest_employees
from routes import router

app = FastAPI(title="NSS Performance Management System", version="1.0.0")

allowed_origins = [
    "http://localhost:5173",
    "http://localhost:3000",
    "https://edge.nicesoftwaresolutions.com",
    "http://edge.nicesoftwaresolutions.com",
]
if os.getenv("FRONTEND_ORIGIN"):
    allowed_origins.append(os.getenv("FRONTEND_ORIGIN"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _is_enabled(env_name, default):
    return os.getenv(env_name, default).strip().lower() not in {"0", "false", "no"}


def _nest_sync_configured():
    if os.getenv("EMPLOYEE_SOURCE", "seed").strip().lower() != "nest":
        return False
    return bool(os.getenv("NEST_API_TOKEN"))


def _run_nest_sync(label):
    if not _nest_sync_configured():
        print(f"NEST employee sync {label} skipped: EMPLOYEE_SOURCE is not nest or NEST_API_TOKEN is missing")
        return

    db = SessionLocal()
    try:
        result = sync_nest_employees(db)
        ensure_employee_credentials(db)
        print(f"NEST employee sync {label} completed: {result}")
    except Exception as exc:
        db.rollback()
        print(f"NEST employee sync {label} skipped: {exc}")
    finally:
        db.close()


def _start_nest_sync_scheduler():
    if not _is_enabled("NEST_SYNC_SCHEDULE_ENABLED", "true"):
        return
    if not _nest_sync_configured():
        return

    sync_time = os.getenv("NEST_SYNC_TIME", "02:00").strip()
    try:
        hour_text, minute_text = sync_time.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except ValueError:
        print(f"NEST employee sync scheduler skipped: invalid NEST_SYNC_TIME '{sync_time}', expected HH:MM")
        return

    timezone = os.getenv("NEST_SYNC_TIMEZONE", "Asia/Kolkata").strip() or "Asia/Kolkata"
    scheduler = BackgroundScheduler(timezone=timezone)
    scheduler.add_job(
        _run_nest_sync,
        CronTrigger(hour=hour, minute=minute, timezone=timezone),
        args=("scheduled",),
        id="daily_nest_employee_sync",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    app.state.nest_sync_scheduler = scheduler
    print(f"NEST employee sync scheduler started: daily at {sync_time} {timezone}")


@app.on_event("startup")
def startup():
    init_db()
    if _is_enabled("NEST_SYNC_ON_STARTUP", "true"):
        _run_nest_sync("startup")
    _start_nest_sync_scheduler()


@app.on_event("shutdown")
def shutdown():
    scheduler = getattr(app.state, "nest_sync_scheduler", None)
    if scheduler:
        scheduler.shutdown(wait=False)

app.include_router(router, prefix="/api")

@app.get("/")
def root():
    return {"message": "NSS PMS API running", "docs": "/docs"}
