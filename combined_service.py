"""Single-container Railway entry point for Scanner + Dashboard.

Render can run the worker and dashboard as separate services via render.yaml.
Railway commonly selects only the Procfile `web` process, so this entry point
runs exactly one scanner thread and one production WSGI server in one process.
"""
from __future__ import annotations

import logging
import os
import threading
import time

from waitress import serve

from dashboard.app import app
from main import main as scanner_main


LOGGER = logging.getLogger("viva-combined-service")


def _run_scanner() -> None:
    """Supervised scanner loop.

    Round-12 incident: one startup exception (a blocked schema migration) killed
    the process on every boot — the dashboard stayed up, so the outage was
    invisible except as silence. The scanner now restarts itself with backoff;
    only a scanner that keeps dying within seconds is allowed to take the
    container down for Railway to rebuild.
    """
    failures = 0
    while True:
        started = time.time()
        try:
            scanner_main()
            return
        except BaseException:
            LOGGER.exception("Scanner loop terminated unexpectedly")
            ran_for = time.time() - started
            failures = failures + 1 if ran_for < 60 else 1
            if failures >= 5:
                LOGGER.error("Scanner failed %d times in a row right after start — "
                             "restarting the container.", failures)
                os._exit(1)
            delay = min(60, 5 * failures)
            LOGGER.warning("Restarting the scanner thread in %ds (failure %d).", delay, failures)
            time.sleep(delay)


def main() -> None:
    scanner = threading.Thread(
        target=_run_scanner,
        name="viva-scanner",
        daemon=True,
    )
    scanner.start()
    app.config["VIVA_SCANNER_THREAD"] = scanner
    port = int(os.getenv("PORT", os.getenv("DASHBOARD_PORT", "8080")))
    threads = int(os.getenv("WEB_THREADS", "6"))
    print(
        f"🌐 Viva combined service listening on 0.0.0.0:{port} "
        f"• scanner thread={scanner.name} • web threads={threads}"
    )
    serve(app, host="0.0.0.0", port=port, threads=threads)


if __name__ == "__main__":
    main()
