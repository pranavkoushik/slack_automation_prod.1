import logging
import os
import sys
import traceback
from pathlib import Path

from fastapi import FastAPI, Header, Response
from fastapi.responses import JSONResponse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from automation import run_automation

LOGGER = logging.getLogger(__name__)

app = FastAPI()


@app.get("/api/cron")
def cron(authorization: str = Header(default="")):
    expected_secret = os.getenv("CRON_SECRET")

    if expected_secret and authorization != f"Bearer {expected_secret}":
        return JSONResponse(
            status_code=401,
            content={"ok": False, "error": "unauthorized"},
        )

    try:
        result = run_automation()
        return {"ok": True, "result": result}
    except Exception as exc:
        LOGGER.error("Automation failed: %s\n%s", exc, traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": str(exc)},
        )
