"""Telegram notification for scan signals.

Sends buy-signal alerts to a Telegram chat via the Bot API. Designed to be
completely optional — if `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` aren't
configured, the notifier silently no-ops and the scanner runs as before.

Usage:
    notifier = TelegramNotifier()
    if notifier.enabled:
        notifier.send_signals(signals, scan_date="2024-01-15")

Environment variables:
    TELEGRAM_BOT_TOKEN   — bot token from @BotFather
    TELEGRAM_CHAT_ID     — target chat id (user, group, or channel)
    TELEGRAM_NOTIFY_ON_EMPTY — "1" / "true" to also send a message when no
                               signals were generated (default: off)
"""
from __future__ import annotations

import os
from html import escape
from typing import Dict, List, Optional

import requests


TELEGRAM_API = "https://api.telegram.org"
# Telegram's hard limit on sendMessage text is 4096 UTF-16 code units; we
# give ourselves a small safety margin.
TELEGRAM_MAX_MESSAGE_LEN = 3800


class TelegramNotifier:
    """Sends scan signals via the Telegram Bot API.

    If the bot token or chat id are missing, every send operation becomes
    a silent no-op, so callers don't need to guard each call.
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        timeout: float = 15.0,
    ):
        self.bot_token = (bot_token if bot_token is not None else os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
        self.chat_id = (chat_id if chat_id is not None else os.getenv("TELEGRAM_CHAT_ID", "")).strip()
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    # ─── low-level send ──────────────────────────────────────────────

    def _post(self, text: str) -> bool:
        url = f"{TELEGRAM_API}/bot{self.bot_token}/sendMessage"
        try:
            resp = requests.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            print(f"[telegram] send failed (network): {e}")
            return False
        if resp.status_code != 200:
            # Don't leak token in logs.
            print(f"[telegram] HTTP {resp.status_code}: {resp.text[:300]}")
            return False
        return True

    def send_message(self, text: str) -> bool:
        """Send one message, auto-splitting on line boundaries if needed."""
        if not self.enabled:
            return False
        if len(text) <= TELEGRAM_MAX_MESSAGE_LEN:
            return self._post(text)
        ok = True
        for chunk in _chunk_text(text, TELEGRAM_MAX_MESSAGE_LEN):
            if not self._post(chunk):
                ok = False
        return ok

    # ─── high-level helpers ─────────────────────────────────────────

    def send_signals(
        self,
        signals: List[Dict],
        scan_date: str,
        notify_on_empty: Optional[bool] = None,
        max_signals: int = 30,
    ) -> bool:
        """Send the signal summary. Returns True on success (or no-op)."""
        if not self.enabled:
            return True  # no-op is success

        if notify_on_empty is None:
            notify_on_empty = _env_bool("TELEGRAM_NOTIFY_ON_EMPTY", default=False)

        if not signals:
            if notify_on_empty:
                return self.send_message(format_no_signal_message(scan_date))
            return True

        return self.send_message(
            format_signals_message(signals, scan_date=scan_date, max_signals=max_signals)
        )

    def send_error(self, scan_date: str, error: str) -> bool:
        if not self.enabled:
            return True
        return self.send_message(format_error_message(scan_date, error))


# ─── formatting ─────────────────────────────────────────────────────

def format_signals_message(
    signals: List[Dict],
    scan_date: str,
    max_signals: int = 30,
) -> str:
    """Format a batch of signals as a single HTML message.

    Signals should already be sorted best-first by the caller.
    """
    n_total = len(signals)
    n_primary = sum(1 for s in signals if s.get("support_category") == "primary")
    n_monitor = sum(1 for s in signals if s.get("support_category") == "monitor")

    lines = [
        f"📊 <b>S&amp;P 500 Support Scan</b> — {escape(scan_date)}",
        f"Found <b>{n_total}</b> signal{'s' if n_total != 1 else ''} "
        f"(🟢 primary: {n_primary}, 🟡 monitor: {n_monitor})",
    ]

    shown = signals[:max_signals]
    for i, s in enumerate(shown, 1):
        lines.append("")  # blank line separator
        lines.append(_format_signal_line(i, s))

    if n_total > max_signals:
        lines.append("")
        lines.append(f"<i>… and {n_total - max_signals} more. See CSV for full list.</i>")

    return "\n".join(lines)


def _format_signal_line(idx: int, s: Dict) -> str:
    ticker = escape(str(s.get("ticker", "?")))
    category = str(s.get("support_category", "?"))
    stype = str(s.get("support_type", "?"))
    score = _num(s.get("score"))
    close = _num(s.get("last_close"))
    zlow = _num(s.get("zone_low"))
    zhigh = _num(s.get("zone_high"))
    atr14 = _num(s.get("atr14"))
    hh = s.get("hh_count", 0)
    hl = s.get("hl_count", 0)

    # Distance from close to zone mid, in ATR multiples — quick read on entry quality.
    zone_mid = (zlow + zhigh) / 2.0 if (zlow and zhigh) else None
    dist_atr = None
    if zone_mid and atr14 and atr14 > 0:
        dist_atr = (close - zone_mid) / atr14

    emoji = "🟢" if category == "primary" else "🟡"
    score_str = f"{score:.1f}" if score else "–"
    close_str = f"${close:.2f}" if close else "–"
    zone_str = f"${zlow:.2f} – ${zhigh:.2f}" if (zlow and zhigh) else "–"
    dist_str = f" ({dist_atr:+.2f} ATR from mid)" if dist_atr is not None else ""

    return (
        f"<b>{idx}. {emoji} {ticker}</b>  "
        f"score <b>{score_str}</b>  <code>[{escape(category)}]</code>\n"
        f"   type: <i>{escape(stype)}</i>\n"
        f"   close: {close_str}{dist_str}\n"
        f"   zone: {zone_str}\n"
        f"   trend: HH {hh} / HL {hl}"
    )


def format_no_signal_message(scan_date: str) -> str:
    return (
        f"📊 <b>S&amp;P 500 Support Scan</b> — {escape(scan_date)}\n\n"
        "No buy signals today."
    )


def format_error_message(scan_date: str, error: str) -> str:
    return (
        f"⚠️ <b>S&amp;P 500 Support Scan</b> — {escape(scan_date)}\n\n"
        f"Scan failed: <code>{escape(str(error)[:600])}</code>"
    )


# ─── utils ──────────────────────────────────────────────────────────

def _num(v) -> float:
    try:
        if v is None:
            return 0.0
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "y", "on")


def _chunk_text(text: str, limit: int) -> List[str]:
    """Split `text` into chunks ≤ `limit` chars, preferring line boundaries."""
    if len(text) <= limit:
        return [text]

    chunks: List[str] = []
    current = ""
    for line in text.split("\n"):
        # If the line itself is longer than the limit, hard-split it.
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]

        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            if current:
                chunks.append(current)
            current = line
        else:
            current = candidate

    if current:
        chunks.append(current)
    return chunks
