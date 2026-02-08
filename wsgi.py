from app import app, _reconcile_on_startup
import scheduler

_reconcile_on_startup()
scheduler.start_scheduler()
