"""Async Gemini advisory for VivaMon messages.

It is deliberately isolated from scoring, confirmation, risk, PnL and execution.
A provider outage can only omit the advisory, never delay or alter a signal.
"""
from __future__ import annotations
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
import requests

_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="viva-gemini")
_LOCK = threading.Lock()
_IN_FLIGHT: set[str] = set()
# ── Round-15 cost guard: the provider answered nothing but HTTPError 107 times
# in a row today, and each attempt still burned a thread, a timeout and log
# noise. After 4 consecutive failures the advisor sleeps 30 minutes (fail-open:
# the advisory is an extra, never part of the signal).
_BREAKER = {"fails": 0, "until": 0.0}
_BREAKER_COOLDOWN = 1800
_BREAKER_THRESHOLD = 4


def breaker_state() -> dict:
    return dict(_BREAKER)


def _breaker_open() -> bool:
    return time.time() < float(_BREAKER["until"])


def _prompt(candidate) -> str:
    md = candidate.metadata or {}
    return f"""تو یک منتور بازار کریپتو هستی. فقط به فارسی، حداکثر 3 بولت کوتاه و مشورتی جواب بده.
این تحلیل، توصیه مالی یا دستور معامله نیست. هیچ قطعیتی نده و Entry/SL/TP سیستم را تغییر نده.
Signal: {candidate.symbol} | {candidate.trigger_timeframe} | {candidate.style} | {candidate.direction}
Setup: {candidate.setup_code} | score: {candidate.score}/10
Entry: {candidate.planned_entry} | First stop: {candidate.sl} | TP1: {candidate.tp1} | TP2: {candidate.tp2}
ATR: {md.get('atr','n/a')} | ADX: {md.get('adx','n/a')} | zone: {md.get('pin_zone_kind') or md.get('poi_type') or 'n/a'}
وظیفه: فقط هم‌جهتی ساختار، ریسک chase، ناحیه حساس ابطال و کیفیت موقعیت را کوتاه توضیح بده."""


def _generate(candidate) -> Optional[str]:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()
    if not key:
        return None
    if _breaker_open():
        return None
    try:
        payload = {"contents": [{"parts": [{"text": _prompt(candidate)}]},],
                   "generationConfig": {"temperature": 0.25, "maxOutputTokens": 280}}
        response = None
        # Direct REST calls do not have the SDK's retry policy. Retry only
        # transient failures (408/429/5xx); never retry auth/permission errors.
        for attempt in range(2):
            response = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                json=payload,
                timeout=20,
            )
            if response.status_code not in (408, 429) and response.status_code < 500:
                break
            if attempt == 0:
                time.sleep(1.0)
        response.raise_for_status()
        data = response.json()
        text = str((((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [{}])[0].get("text") or "").strip()
        _BREAKER["fails"] = 0
        return text[:1200] or None
    except Exception as exc:
        _BREAKER["fails"] = int(_BREAKER["fails"]) + 1
        if _BREAKER["fails"] >= _BREAKER_THRESHOLD and not _breaker_open():
            _BREAKER["until"] = time.time() + _BREAKER_COOLDOWN
            print(f"Gemini advisory circuit opened for {_BREAKER_COOLDOWN // 60} min "
                  f"after {_BREAKER['fails']} consecutive failures")
        else:
            print(f"Gemini advisory unavailable {candidate.signal_id}: {type(exc).__name__}")
        return None


def request_advisory_async(candidate) -> None:
    """Generate after candidate persistence; never blocks scanner or Telegram."""
    if not os.getenv("GEMINI_API_KEY") or (candidate.metadata or {}).get("gemini_advisory"):
        return
    signal_id = str(candidate.signal_id)
    with _LOCK:
        if signal_id in _IN_FLIGHT:
            return
        _IN_FLIGHT.add(signal_id)

    def work():
        try:
            advisory = _generate(candidate)
            if advisory:
                candidate.metadata["gemini_advisory"] = advisory
                try:
                    from database.candidate_store import update_candidate
                    update_candidate(candidate)
                except Exception as exc:
                    print(f"Gemini advisory persistence warning {signal_id}: {exc}")
        finally:
            with _LOCK:
                _IN_FLIGHT.discard(signal_id)
    _POOL.submit(work)
