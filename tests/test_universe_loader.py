"""Unit tests for the ticker.txt universe loader.

Run:
    python -m tests.test_universe_loader
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.universe_loader import load_sp500_tickers


def _write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def test_reads_simple_list():
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "ticker.txt")
        _write(p, "AAPL\nMSFT\nGOOGL\n")
        tickers = load_sp500_tickers(p)
        assert tickers == ["AAPL", "MSFT", "GOOGL"], tickers
    print("[OK] simple list.")


def test_uppercases_and_strips():
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "ticker.txt")
        _write(p, "  aapl  \n\tmsft\n googl \n")
        tickers = load_sp500_tickers(p)
        assert tickers == ["AAPL", "MSFT", "GOOGL"], tickers
    print("[OK] uppercasing + whitespace stripping.")


def test_ignores_comments_and_blanks():
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "ticker.txt")
        _write(
            p,
            "# This is a comment\n"
            "\n"
            "AAPL\n"
            "   # indented comment\n"
            "MSFT\n"
            "\n"
            "GOOGL\n",
        )
        tickers = load_sp500_tickers(p)
        assert tickers == ["AAPL", "MSFT", "GOOGL"], tickers
    print("[OK] comments + blank lines ignored.")


def test_strips_inline_comments():
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "ticker.txt")
        _write(p, "AAPL  # apple\nMSFT#microsoft\nGOOGL\n")
        tickers = load_sp500_tickers(p)
        assert tickers == ["AAPL", "MSFT", "GOOGL"], tickers
    print("[OK] inline comments stripped.")


def test_dedupes_preserving_order():
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "ticker.txt")
        _write(p, "AAPL\nMSFT\naapl\nGOOGL\nMSFT\n")
        tickers = load_sp500_tickers(p)
        assert tickers == ["AAPL", "MSFT", "GOOGL"], tickers
    print("[OK] dedup preserves first occurrence.")


def test_dot_tickers_preserved():
    # Polygon format: BRK.B, BF.B — the dot must survive.
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "ticker.txt")
        _write(p, "BRK.B\nBF.B\nAAPL\n")
        tickers = load_sp500_tickers(p)
        assert tickers == ["BRK.B", "BF.B", "AAPL"], tickers
    print("[OK] dotted tickers preserved.")


def test_comma_and_space_separated_on_one_line():
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "ticker.txt")
        _write(p, "AAPL, MSFT GOOGL\n")
        tickers = load_sp500_tickers(p)
        assert tickers == ["AAPL", "MSFT", "GOOGL"], tickers
    print("[OK] comma/space-separated on a single line.")


def test_missing_file_raises_clearly():
    missing = "/tmp/this_definitely_does_not_exist_abc123.txt"
    try:
        load_sp500_tickers(missing)
    except FileNotFoundError as e:
        # Make sure the error message includes the path and a hint to
        # create the file — this is how users will discover the fix.
        msg = str(e)
        assert missing in msg, msg
        assert "one ticker per line" in msg, msg
    else:
        raise AssertionError("expected FileNotFoundError for missing file")
    print("[OK] missing-file error is clear.")


def test_empty_file_returns_empty_list():
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "ticker.txt")
        _write(p, "# only comments\n\n# nothing useful\n")
        tickers = load_sp500_tickers(p)
        assert tickers == [], tickers
    print("[OK] all-comments file returns empty list.")


def test_real_starter_file_exists_and_loads():
    """The shipped ticker.txt at the repo root should be readable."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "ticker.txt")
    assert os.path.exists(path), f"starter ticker.txt missing at {path}"
    tickers = load_sp500_tickers(path)
    # Sanity: should be ~500 tickers, all uppercase, and include a few
    # ubiquitous names.
    assert len(tickers) > 400, f"expected > 400 tickers, got {len(tickers)}"
    for sym in ["AAPL", "MSFT", "GOOGL"]:
        assert sym in tickers, f"{sym} missing from shipped ticker.txt"
    assert all(t == t.upper() for t in tickers), "found non-uppercase ticker"
    print(f"[OK] shipped ticker.txt loaded ({len(tickers)} tickers).")


def main():
    test_reads_simple_list()
    test_uppercases_and_strips()
    test_ignores_comments_and_blanks()
    test_strips_inline_comments()
    test_dedupes_preserving_order()
    test_dot_tickers_preserved()
    test_comma_and_space_separated_on_one_line()
    test_missing_file_raises_clearly()
    test_empty_file_returns_empty_list()
    test_real_starter_file_exists_and_loads()
    print("\n[OK] all universe_loader tests passed.")


if __name__ == "__main__":
    main()
