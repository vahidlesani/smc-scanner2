"""Single-container Railway entry point for Scanner + Dashboard.

Render can run the worker and dashboard as separate services via render.yaml.
Railway commonly selects only the Procfile `web` process, so this entry point
runs exactly one scanner thread and one production WSGI server in one process.
"""
from __future__ import annotations

import logging
import os
import threading

from waitress import serve

from dashboard.app import app
from main import main as scanner_main


LOGGER = logging.getLogger("viva-combined-service")


def _run_scanner() -> None:
    try:
        scanner_main()
    except BaseException:
        LOGGER.exception("Scanner thread terminated unexpectedly")
        # A dashboard-only process would look healthy while signals are dead.
        # Exit hard so Railway restarts the full service.
        os._exit(1)


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
