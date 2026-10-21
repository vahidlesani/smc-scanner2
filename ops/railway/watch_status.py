#!/usr/bin/env python3
"""Check Railway's public platform status and optionally notify Telegram.

Designed for the GitHub Actions watcher in ``railway-status-watch.yml`` so the
watcher remains alive even while Railway itself is unavailable.  No Railway
token is needed and secret values are never printed.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping

API = "https://backboard.railway.com/graphql/v2"
QUERY = """
query VivaRailwayStatus {
  platformStatus {
    isStable
    incident { id message status createdAt url }
    maintenance { id }
  }
}
"""


def _post_json(url: str, payload: Mapping[str, Any], timeout: int = 30) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(dict(payload)).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "viva-railway-status-watch/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_status(timeout: int = 30) -> dict:
    body = _post_json(API, {"query": QUERY}, timeout=timeout)
    errors = body.get("errors") or []
    if errors:
        message = str((errors[0] or {}).get("message") or errors[0])[:240]
        raise RuntimeError(f"Railway GraphQL error: {message}")
    status = ((body.get("data") or {}).get("platformStatus") or {})
    if "isStable" not in status:
        raise RuntimeError("Railway response did not contain platformStatus.isStable")
    return status


def status_fields(status: Mapping[str, Any]) -> dict[str, str]:
    incident = status.get("incident") or {}
    maintenance = status.get("maintenance") or {}
    stable = bool(status.get("isStable"))
    # Railway's own isStable flag is the authoritative restore signal.  An
    # active maintenance object also keeps the migration paused.
    ready = stable and not maintenance
    return {
        "ready": "true" if ready else "false",
        "stable": "true" if stable else "false",
        "incident_id": str(incident.get("id") or ""),
        "incident_status": str(incident.get("status") or ""),
        "incident_message": str(incident.get("message") or ""),
        "incident_url": str(incident.get("url") or ""),
        "maintenance_id": str(maintenance.get("id") or ""),
    }


def write_github_output(path: str, fields: Mapping[str, str]) -> None:
    """Write simple single-line values to GITHUB_OUTPUT safely."""
    target = Path(path)
    with target.open("a", encoding="utf-8") as stream:
        for key, value in fields.items():
            clean = str(value).replace("\r", " ").replace("\n", " ")
            stream.write(f"{key}={clean}\n")


def telegram_text(fields: Mapping[str, str]) -> str:
    incident = fields.get("incident_id") or "—"
    prior = fields.get("incident_status") or "—"
    url = fields.get("incident_url") or "https://status.railway.com/"
    return (
        "✅ <b>Railway دوباره آماده شد</b>\n\n"
        f"وضعیت پلتفرم: <b>STABLE</b>\n"
        f"رخداد: <code>{html.escape(incident)}</code> ({html.escape(prior)})\n"
        f"<a href=\"{html.escape(url, quote=True)}\">صفحهٔ رسمی وضعیت</a>\n\n"
        "واچر ۱۰ دقیقه‌ای خاموش شد تا پیام تکراری نیاید.\n"
        "⚠️ مهاجرت فقط بعد از جایگزینی همهٔ رمزهای افشاشده انجام می‌شود."
    )


def send_telegram(token: str, chat_id: str, text: str, timeout: int = 30) -> dict:
    token = str(token or "").strip()
    chat_id = str(chat_id or "").strip()
    if not token:
        raise RuntimeError("RAILWAY_STATUS_TELEGRAM_TOKEN is empty")
    if not chat_id:
        raise RuntimeError("RAILWAY_STATUS_CHAT_ID is empty")
    # The token is only placed in the HTTPS request target; it is never logged.
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Telegram's error body cannot contain the request URL/token; keep only
        # its short description and never stringify the original request.
        try:
            body = json.loads(exc.read().decode("utf-8"))
            detail = str(body.get("description") or "HTTP error")[:180]
        except Exception:
            detail = f"HTTP {exc.code}"
        raise RuntimeError(f"Telegram send failed: {detail}") from None
    if not body.get("ok"):
        raise RuntimeError(
            "Telegram send failed: " + str(body.get("description") or "unknown")[:180]
        )
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--github-output", default=os.getenv("GITHUB_OUTPUT", ""))
    parser.add_argument(
        "--notify-ready",
        action="store_true",
        help="send one Telegram message when Railway reports stable",
    )
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args(argv)

    try:
        status = fetch_status(timeout=max(5, args.timeout))
        fields = status_fields(status)
        if args.github_output:
            write_github_output(args.github_output, fields)
        incident = fields["incident_id"] or "none"
        state = fields["incident_status"] or "none"
        print(
            f"Railway stable={fields['stable']} ready={fields['ready']} "
            f"incident={incident} status={state}"
        )
        if args.notify_ready and fields["ready"] == "true":
            send_telegram(
                os.getenv("RAILWAY_STATUS_TELEGRAM_TOKEN", ""),
                os.getenv("RAILWAY_STATUS_CHAT_ID", ""),
                telegram_text(fields),
                timeout=max(5, args.timeout),
            )
            print("Telegram restore notification sent.")
        return 0
    except Exception as exc:
        # No URL-bearing urllib exception is printed, protecting bot tokens.
        print(f"watch error: {type(exc).__name__}: {str(exc)[:300]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
