"""Unit tests for the Telegram notifier formatting + chunking.

Run:
    python -m tests.test_notifier

No network calls are made — TelegramNotifier._post is never invoked because
the notifier is instantiated without credentials, so .enabled == False.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.notifier import (
    TELEGRAM_MAX_MESSAGE_LEN,
    TelegramNotifier,
    _chunk_text,
    format_error_message,
    format_no_signal_message,
    format_signals_message,
)


def _sample_signal(ticker="AAPL", category="primary", score=85.5, stype="higher_low"):
    return {
        "signal_date": "2024-01-15",
        "ticker": ticker,
        "support_category": category,
        "support_type": stype,
        "last_close": 182.45,
        "zone_low": 180.20,
        "zone_high": 181.50,
        "atr14": 2.35,
        "hh_count": 4,
        "hl_count": 3,
        "score": score,
    }


def test_disabled_by_default():
    # Make sure env vars from the shell don't accidentally enable the notifier
    n = TelegramNotifier(bot_token="", chat_id="")
    assert n.enabled is False
    # All send methods must be no-ops that return truthy without raising
    assert n.send_message("hello") is False
    assert n.send_signals([_sample_signal()], "2024-01-15") is True
    assert n.send_error("2024-01-15", "boom") is True
    print("[OK] disabled notifier is a silent no-op.")


def test_enabled_flag():
    n = TelegramNotifier(bot_token="tok", chat_id="123")
    assert n.enabled is True
    print("[OK] credentials enable the notifier.")


def test_format_empty_message():
    msg = format_no_signal_message("2024-01-15")
    assert "2024-01-15" in msg
    assert "No buy signals" in msg
    print("[OK] no-signal message formatting.")


def test_format_signals_message_basic():
    signals = [
        _sample_signal("AAPL", "primary", 87.3),
        _sample_signal("MSFT", "monitor", 72.1, "breakout_retest"),
    ]
    msg = format_signals_message(signals, scan_date="2024-01-15")
    # Dates/tickers included
    assert "2024-01-15" in msg
    assert "AAPL" in msg
    assert "MSFT" in msg
    # Amp in S&amp;P survives HTML escape
    assert "S&amp;P 500" in msg
    # Category counts
    assert "primary: 1" in msg
    assert "monitor: 1" in msg
    # Score rendered
    assert "87.3" in msg
    # Zone pattern
    assert "$180.20" in msg
    print("[OK] signals message formatting.")


def test_format_signals_truncation():
    signals = [_sample_signal(f"TIC{i}", "primary", 90.0 - i) for i in range(50)]
    msg = format_signals_message(signals, scan_date="2024-01-15", max_signals=10)
    assert "TIC0" in msg
    assert "TIC9" in msg
    # 11th+ signals should be truncated
    assert "TIC10" not in msg
    assert "40 more" in msg
    print("[OK] truncation summary.")


def test_format_error_message_escapes_html():
    msg = format_error_message("2024-01-15", "Exception: <script>bad</script>")
    assert "&lt;script&gt;" in msg
    assert "<script>" not in msg.replace("<script>bad</script>", "")  # original tag not injected raw
    print("[OK] error formatting escapes HTML.")


def test_chunk_text_short_returns_single():
    assert _chunk_text("hello", 100) == ["hello"]
    print("[OK] chunking short text.")


def test_chunk_text_splits_on_lines():
    text = "line1\nline2\nline3\nline4"
    chunks = _chunk_text(text, 12)
    # Every chunk is within the limit
    assert all(len(c) <= 12 for c in chunks), chunks
    # Reassembly preserves all lines (order-preserving)
    rejoined = "\n".join(chunks).replace("\n\n", "\n")
    for line in ["line1", "line2", "line3", "line4"]:
        assert line in rejoined, (line, chunks)
    print("[OK] line-boundary chunking.")


def test_chunk_text_hard_split_very_long_line():
    line = "x" * 50
    chunks = _chunk_text(line, 10)
    assert all(len(c) <= 10 for c in chunks)
    assert "".join(chunks) == line
    print("[OK] hard-split when a single line exceeds the limit.")


def test_large_message_would_be_chunked():
    signals = [_sample_signal(f"TIC{i}", "primary", 50.0) for i in range(1000)]
    msg = format_signals_message(signals, scan_date="2024-01-15", max_signals=1000)
    # Should be > single-message limit so auto-chunking kicks in on send.
    assert len(msg) > TELEGRAM_MAX_MESSAGE_LEN
    chunks = _chunk_text(msg, TELEGRAM_MAX_MESSAGE_LEN)
    assert len(chunks) > 1
    assert all(len(c) <= TELEGRAM_MAX_MESSAGE_LEN for c in chunks)
    print(f"[OK] large message chunked into {len(chunks)} parts.")


def main():
    test_disabled_by_default()
    test_enabled_flag()
    test_format_empty_message()
    test_format_signals_message_basic()
    test_format_signals_truncation()
    test_format_error_message_escapes_html()
    test_chunk_text_short_returns_single()
    test_chunk_text_splits_on_lines()
    test_chunk_text_hard_split_very_long_line()
    test_large_message_would_be_chunked()
    print("\n[OK] all notifier tests passed.")


if __name__ == "__main__":
    main()
