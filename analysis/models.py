"""Shared domain models used by live scanner, Telegram and backtest."""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat(timespec="seconds")


def _native(value: Any) -> Any:
    """Convert numpy/pandas values to JSON-safe Python values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if isinstance(value, dict):
        return {str(k): _native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_native(v) for v in value]
    return str(value)


@dataclass
class EvidenceItem:
    key: str
    title: str
    detail: str
    confirmed: bool
    points: int = 0
    value: Optional[float] = None
    level: Optional[float] = None
    timeframe: str = ""


@dataclass
class SignalCandidate:
    signal_id: str
    symbol: str
    style: str
    setup_code: str
    setup_name: str
    strategy_fa: str
    direction: str
    score: int
    status: str
    entry_zone_bottom: float
    entry_zone_top: float
    planned_entry: float
    sl: float
    tp1: float
    tp2: float
    rr_tp1: float
    rr_tp2: float
    bias: str
    trigger_timeframe: str
    evidence: List[EvidenceItem] = field(default_factory=list)
    confirmations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    mandatory_gates: Dict[str, bool] = field(default_factory=dict)
    market: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    approaching_sent: bool = False
    created_at: str = field(default_factory=iso_now)
    expires_at: str = ""
    confirmed_at: str = ""

    @property
    def zone_mid(self) -> float:
        return (self.entry_zone_bottom + self.entry_zone_top) / 2.0

    @property
    def execution_ready(self) -> bool:
        return bool(self.mandatory_gates) and all(self.mandatory_gates.values())

    def to_dict(self) -> Dict[str, Any]:
        return _native(asdict(self))

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SignalCandidate":
        payload = dict(data)
        payload["evidence"] = [
            item if isinstance(item, EvidenceItem) else EvidenceItem(**item)
            for item in payload.get("evidence", [])
        ]
        return cls(**payload)

    @classmethod
    def from_json(cls, value: str) -> "SignalCandidate":
        return cls.from_dict(json.loads(value))


def generate_viva_signal_id(symbol: str, style: str, setup_code: str) -> str:
    raw_symbol = symbol.upper().replace("USDT", "").replace(".P", "")
    clean_symbol = "".join(ch for ch in raw_symbol if ch.isalnum())[:16]
    style_code = "SW" if style.upper() == "SWING" else "SC"
    setup = "".join(ch for ch in setup_code.upper() if ch.isalnum())[:8]
    ts = utc_now().strftime("%m%d%H%M")
    random_code = uuid.uuid4().hex[:4].upper()
    return f"viva-{clean_symbol}-{style_code}-{setup}-{ts}-{random_code}"


def generate_viva_public_code(setup_code: str = "", style: str = "") -> str:
    """Stable human-facing lineage code; never embeds update time or symbol."""
    import secrets
    label_map = {
        "PINVAL": "PINBAR", "PINWALLQ": "PINWALLQ", "TLBREAK": "TLBREAK",
        "ALBROX": "ALBROX", "P1234": "P1234", "LSR": "LSR", "SDR": "SDR",
        "BOS1": "BOS", "IFVG": "IFVG", "TLR": "TLR",
    }
    raw = "".join(ch for ch in str(setup_code).upper() if ch.isalnum())[:12]
    label = label_map.get(raw, raw or "SETUP")
    # Human-readable proposal only. Before any Telegram publication it is
    # atomically reserved in PostgreSQL by `reserve_public_code`, so randomness
    # never becomes the uniqueness guarantee.
    return f"VIVA-{label}-K{secrets.randbelow(900000) + 100000}"
