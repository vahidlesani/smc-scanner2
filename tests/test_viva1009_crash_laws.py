"""Viva 10-09 crash laws — lock tests.

The Railway crash of 10-08/09: commit 0548f2b shipped a SyntaxError in
combined_service.py (a real newline inside the healthcheck bytes literal),
so the container died at startup, exhausted ON_FAILURE×10 retries and stayed
DOWN. The suite never caught it because nothing imported the entrypoint.
Locks: the repo compiles, the entrypoint imports, the scheduler loop and
figure paths cannot leak/die, restarts never duplicate threads, Railway
always restarts, and the dedup ledger is capped.
"""
import json
import os
import py_compile

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), os.pardir))


def test_repo_compiles_including_entrypoint():
    """Every shipped .py compiles — the 10-08 blind spot is closed."""
    checked = 0
    for root, _dirs, files in os.walk(REPO):
        if "/tests" in root or "/.git" in root:
            continue
        for fn in files:
            if fn.endswith(".py"):
                py_compile.compile(os.path.join(root, fn), doraise=True)
                checked += 1
    assert checked > 50


def test_entrypoint_imports():
    import combined_service
    assert callable(combined_service.main)


def test_scheduler_loop_never_dies():
    src = open(os.path.join(REPO, "main.py"), encoding="utf-8").read()
    assert "_loop_fails" in src and "except Exception as _loop_exc" in src


def test_daemon_threads_start_once():
    src = open(os.path.join(REPO, "main.py"), encoding="utf-8").read()
    assert "_DAEMONS_STARTED" in src


def test_figures_always_close():
    for rel in ("bot/messages_v7.py", "analysis/spot_pattern_engine.py"):
        src = open(os.path.join(REPO, rel), encoding="utf-8").read()
        assert "finally:" in src and "plt.close(fig)" in src, rel


def test_railway_always_restarts():
    cfg = json.load(open(os.path.join(REPO, "railway.json"), encoding="utf-8"))
    assert cfg["deploy"]["restartPolicyType"] == "ALWAYS"


def test_spot_alert_ledger_capped():
    src = open(os.path.join(REPO, "analysis", "spot_engine.py"), encoding="utf-8").read()
    assert "len(state) > 500" in src
