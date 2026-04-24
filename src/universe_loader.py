"""Load the ticker universe from a user-managed text file.

The file is a plain text list — one ticker per line. Blank lines and
lines starting with `#` are ignored so users can group / comment.

Example ticker.txt:
    # Tech
    AAPL
    MSFT
    GOOGL

    # Financials
    JPM
    BAC

This is intentionally simple: the file lives at the repo root and is
updated by hand (or via GitHub's web UI). There is NO automatic fetch
from Wikipedia or any other source — if the file is missing, the scan
fails loudly so you notice.
"""
import os
from typing import List


def load_sp500_tickers(path: str) -> List[str]:
    """Read tickers from a plain-text file.

    Returns an uppercase, de-duplicated list preserving file order.
    Raises FileNotFoundError with a helpful message if the file is missing.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Ticker file not found: {path}\n"
            f"Create a plain text file at '{path}' with one ticker per line.\n"
            f"Blank lines and '# comments' are OK. Example:\n"
            f"    # Tech\n"
            f"    AAPL\n"
            f"    MSFT\n"
        )

    tickers: List[str] = []
    seen: set = set()
    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            # Strip inline comments: "AAPL  # apple" -> "AAPL"
            token = line.split("#", 1)[0].strip()
            if not token:
                continue
            # Tolerate accidental commas / whitespace separators on one line.
            for part in token.replace(",", " ").split():
                sym = part.strip().upper()
                if sym and sym not in seen:
                    seen.add(sym)
                    tickers.append(sym)

    return tickers
