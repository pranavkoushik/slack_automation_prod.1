import json
import logging
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from automation import run_automation

LOGGER = logging.getLogger(__name__)


class handler(BaseHTTPRequestHandler):

    def _send_json(self, status_code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        LOGGER.info(format, *args)

    def do_GET(self) -> None:
        expected_secret = os.getenv("CRON_SECRET")
        auth_header = self.headers.get("authorization")

        if expected_secret and auth_header != f"Bearer {expected_secret}":
            self._send_json(401, {"ok": False, "error": "unauthorized"})
            return

        try:
            result = run_automation()
            self._send_json(200, {"ok": True, "result": result})
        except Exception as exc:
            LOGGER.error("Automation failed: %s\n%s", exc, traceback.format_exc())
            self._send_json(500, {"ok": False, "error": str(exc)})

    def do_POST(self) -> None:
        self._send_json(405, {"ok": False, "error": "method_not_allowed"})
