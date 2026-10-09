"""Single-container Railway entry point for Scanner + Lean Web Healthcheck.

Railway selects the Procfile  process, requiring a listening HTTP port.
When DISABLE_WEB_APP=1 (or lean mode), it serves a micro, near-zero-overhead
healthcheck endpoint instead of the heavy multi-threaded Flask dashboard,
massively reducing CPU and memory consumption.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from wsgiref.simple_server import make_server

from main import main as scanner_main

LOGGER = logging.getLogger("viva-combined-service")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def _run_scanner() -> None:
    """Supervised resilient scanner loop.
    Never allows an unhandled exception to kill the entire container with os._exit(1).
    """
    failures = 0
    while True:
        started = time.time()
        try:
            import main as _m  # 10-09: a stale _SHUTDOWN would exit instantly
            _m._SHUTDOWN = False
            import threading as _th
            LOGGER.info("scanner (re)start — live threads: %d",
                        len(_th.enumerate()))
            scanner_main()
            return
        except BaseException as exc:
            LOGGER.exception("Scanner loop exception: %s", exc)
            ran_for = time.time() - started
            failures = failures + 1 if ran_for < 60 else 1
            delay = min(60, 5 * failures)
            LOGGER.warning("Recovering scanner thread in %ds (failure %d)...", delay, failures)
            time.sleep(delay)


def _lean_wsgi_app(environ, start_response):
    """Minimalistic WSGI application responding to Railway healthchecks with ~0% CPU/RAM."""
    path = environ.get("PATH_INFO", "/")
    status = "200 OK"
    headers = [("Content-Type", "application/json")]
    start_response(status, headers)
    return [b'{"status":"ok","service":"viva-scanner","web_mode":"lean"}']


def main() -> None:
    scanner = threading.Thread(
        target=_run_scanner,
        name="viva-scanner",
        daemon=True,
    )
    scanner.start()

    port = int(os.getenv("PORT", os.getenv("DASHBOARD_PORT", "8080")))
    enable_heavy_dashboard = os.getenv("ENABLE_DASHBOARD", "0").strip().lower() in {"1", "true", "yes"}

    if enable_heavy_dashboard:
        try:
            from waitress import serve
            from dashboard.app import app
            app.config["VIVA_SCANNER_THREAD"] = scanner
            threads = int(os.getenv("WEB_THREADS", "2"))
            LOGGER.info("🌐 Starting full dashboard on port %d (%d threads)", port, threads)
            serve(app, host="0.0.0.0", port=port, threads=threads)
            return
        except Exception as e:
            LOGGER.warning("Failed to load full dashboard, falling back to lean healthcheck: %s", e)

    LOGGER.info("🌐 Starting ultra-lean healthcheck server on port %d (web-app muted to save Railway quota)", port)
    httpd = make_server("0.0.0.0", port, _lean_wsgi_app)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
