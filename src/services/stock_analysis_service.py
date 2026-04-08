"""Stock quote/analysis service built on yfinance.

This module keeps stock parsing deterministic:
- price lookup requests -> direct quote text
- analysis/prediction requests -> technical indicators for LLM
"""
from __future__ import annotations

import importlib
import subprocess
import sys
from typing import Optional


def _u(s: str) -> str:
    """Decode ASCII unicode-escape literals to Korean text."""
    return s.encode("ascii").decode("unicode_escape")


KOREAN_STOCK_MAP: dict[str, tuple[str, str]] = {
    _u("\\uc0bc\\uc131\\uc804\\uc790"): ("005930.KS", _u("\\uc0bc\\uc131\\uc804\\uc790")),
    _u("\\uc0bc\\uc131"): ("005930.KS", _u("\\uc0bc\\uc131\\uc804\\uc790")),
    "samsung": ("005930.KS", _u("\\uc0bc\\uc131\\uc804\\uc790")),
    _u("\\uc5d0\\uc2a4\\ucf00\\uc774\\ud558\\uc774\\ub2c9\\uc2a4"): ("000660.KS", _u("\\uc5d0\\uc2a4\\ucf00\\uc774\\ud558\\uc774\\ub2c9\\uc2a4")),
    _u("\\ud558\\uc774\\ub2c9\\uc2a4"): ("000660.KS", _u("\\uc5d0\\uc2a4\\ucf00\\uc774\\ud558\\uc774\\ub2c9\\uc2a4")),
    _u("\\ub124\\uc774\\ubc84"): ("035420.KS", "NAVER"),
    "naver": ("035420.KS", "NAVER"),
    _u("\\uce74\\uce74\\uc624"): ("035720.KQ", _u("\\uce74\\uce74\\uc624")),
    _u("\\ud604\\ub300\\ucc28"): ("005380.KS", _u("\\ud604\\ub300\\uc790\\ub3d9\\ucc28")),
    _u("\\uae30\\uc544"): ("000270.KS", _u("\\uae30\\uc544")),
    _u("\\ucf54\\uc2a4\\ud53c"): ("^KS11", "KOSPI"),
    "kospi": ("^KS11", "KOSPI"),
    _u("\\ucf54\\uc2a4\\ub2e5"): ("^KQ11", "KOSDAQ"),
    "kosdaq": ("^KQ11", "KOSDAQ"),
    _u("\\uc560\\ud50c"): ("AAPL", "Apple"),
    "apple": ("AAPL", "Apple"),
    "aapl": ("AAPL", "Apple"),
    _u("\\uc5d4\\ube44\\ub514\\uc544"): ("NVDA", "NVIDIA"),
    "nvidia": ("NVDA", "NVIDIA"),
    "nvda": ("NVDA", "NVIDIA"),
    _u("\\ud14c\\uc2ac\\ub77c"): ("TSLA", "Tesla"),
    "tesla": ("TSLA", "Tesla"),
    "tsla": ("TSLA", "Tesla"),
    _u("\\ub9c8\\uc774\\ud06c\\ub85c\\uc18c\\ud504\\ud2b8"): ("MSFT", "Microsoft"),
    "microsoft": ("MSFT", "Microsoft"),
    "msft": ("MSFT", "Microsoft"),
}

ANALYSIS_ACTION_KEYWORDS = [
    _u("\\ubd84\\uc11d"),
    _u("\\uae30\\uc220\\uc801 \\ubd84\\uc11d"),
    _u("\\uc608\\uce21"),
    _u("\\uc804\\ub9dd"),
    "rsi",
    "macd",
    _u("\\ubcfc\\ub9b0\\uc800"),
]

PRICE_ACTION_KEYWORDS = [
    _u("\\uc8fc\\uac00"),
    _u("\\uc2dc\\uc138"),
    _u("\\uac00\\uaca9"),
    _u("\\uc5bc\\ub9c8"),
    _u("\\ud604\\uc7ac\\uac00"),
]

STOCK_CONTEXT_KEYWORDS = [
    _u("\\uc8fc\\uc2dd"),
    _u("\\uc885\\ubaa9"),
    _u("\\uc8fc\\uac00"),
    _u("\\ucf54\\uc2a4\\ud53c"),
    _u("\\ucf54\\uc2a4\\ub2e5"),
]


def _run_install_command(command: list[str], package_name: str) -> tuple[bool, Optional[str]]:
    try:
        result = subprocess.run(
            command + [package_name],
            capture_output=True,
            text=True,
            timeout=180,
        )
    except Exception as exc:
        return False, f"자동 설치 실행 실패: {exc}"

    if result.returncode == 0:
        return True, None

    stderr = (result.stderr or "").strip()
    stdout = (result.stdout or "").strip()
    raw_details = stderr or stdout or "원인을 확인하지 못했습니다."
    lines = [line.strip() for line in raw_details.splitlines() if line.strip()]
    details = " / ".join(lines[-3:]) if lines else raw_details
    return False, f"자동 설치 실패: {details}"


def _auto_install_package(package_name: str) -> tuple[bool, Optional[str]]:
    """Try installing a missing package in dev/runtime Python."""
    ok, error = _run_install_command([sys.executable, "-m", "pip", "install"], package_name)
    if ok:
        return True, None

    if not getattr(sys, "frozen", False):
        return False, error

    for base in (["py", "-m", "pip", "install"], ["python", "-m", "pip", "install"]):
        ok, fallback_error = _run_install_command(base, package_name)
        if ok:
            return True, None
        error = fallback_error

    return False, error


def _import_yfinance():
    """Import yfinance, attempting one-time auto install when missing."""
    try:
        return importlib.import_module("yfinance"), None
    except ImportError:
        ok, install_error = _auto_install_package("yfinance")
        if not ok:
            if install_error:
                return None, (
                    "`yfinance` 패키지가 설치되지 않았고 자동 설치에도 실패했습니다.\n"
                    f"{install_error}"
                )
            return None, "`yfinance` 패키지가 설치되지 않았습니다."
        try:
            return importlib.import_module("yfinance"), None
        except Exception as exc:
            return None, f"`yfinance` 설치 후 로드에 실패했습니다: {exc}"


def _has_stock_context(text: str) -> bool:
    t = text.lower()
    if any(k in t for k in STOCK_CONTEXT_KEYWORDS):
        return True
    return any(name in t for name in KOREAN_STOCK_MAP)


def is_stock_analysis_query(text: str) -> bool:
    t = text.lower()
    has_action = any(k in t for k in ANALYSIS_ACTION_KEYWORDS)
    return has_action and _has_stock_context(t)


def is_stock_price_query(text: str) -> bool:
    t = text.lower()
    has_action = any(k in t for k in PRICE_ACTION_KEYWORDS)
    return has_action and _has_stock_context(t)


def _resolve_ticker(query: str) -> tuple[Optional[str], Optional[str]]:
    q_lower = query.lower().replace(" ", "")
    for name, (ticker, official_name) in KOREAN_STOCK_MAP.items():
        if name.replace(" ", "") in q_lower:
            return ticker, official_name
    return None, None


def _calc_rsi(close, period: int = 14):
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window=period).mean()
    loss = (-delta.clip(upper=0)).rolling(window=period).mean()
    rs = gain / loss.replace(0, float("inf"))
    return 100 - (100 / (1 + rs))


def _calc_macd(close, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line, macd_line - signal_line


def _calc_bollinger(close, period: int = 20, std_mult: float = 2.0):
    sma = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    return sma + std_mult * std, sma, sma - std_mult * std


def run_stock_quote(query: str) -> tuple[Optional[str], Optional[str]]:
    yf, import_error = _import_yfinance()
    if import_error:
        return None, import_error

    ticker_code, company_name = _resolve_ticker(query)
    if not ticker_code:
        return None, _u("\\uc885\\ubaa9\\uba85\\uc744 \\uc778\\uc2dd\\ud558\\uc9c0 \\ubabb\\ud588\\uc2b5\\ub2c8\\ub2e4. \\uc608: '\\uc0bc\\uc131\\uc804\\uc790 \\uc8fc\\uac00 \\uc54c\\ub824\\uc918'")

    try:
        df = yf.Ticker(ticker_code).history(period="5d", interval="1d")
        if df.empty:
            return None, _u("\\uac00\\uaca9 \\ub370\\uc774\\ud130\\ub97c \\uac00\\uc838\\uc624\\uc9c0 \\ubabb\\ud588\\uc2b5\\ub2c8\\ub2e4.")

        close = df["Close"]
        current = float(close.iloc[-1])
        prev = float(close.iloc[-2]) if len(close) > 1 else current
        change = current - prev
        change_pct = (change / prev * 100) if prev else 0.0

        is_us = ticker_code.isalpha() and len(ticker_code) <= 5 and not ticker_code.startswith("^")
        if is_us:
            price = f"${current:,.2f}"
            delta = f"{change:+.2f}"
        else:
            price = f"{current:,.0f}원"
            delta = f"{change:+,.0f}원"

        text = (
            f"[{company_name} ({ticker_code})]\\n"
            f"현재가: {price}\n"
            f"전일 대비: {delta} ({change_pct:+.2f}%)"
        )
        return text, None
    except Exception as exc:
        return None, f"yfinance quote error: {exc}"


def run_technical_analysis(query: str) -> tuple[Optional[str], Optional[str]]:
    yf, import_error = _import_yfinance()
    if import_error:
        return None, import_error

    ticker_code, company_name = _resolve_ticker(query)
    if not ticker_code:
        return None, _u("\\uc885\\ubaa9\\uba85\\uc744 \\uc778\\uc2dd\\ud558\\uc9c0 \\ubabb\\ud588\\uc2b5\\ub2c8\\ub2e4. \\uc608: '\\uc0bc\\uc131\\uc804\\uc790 \\uc8fc\\uac00 \\uc608\\uce21\\ud574\\uc918'")

    try:
        df = yf.Ticker(ticker_code).history(period="3mo")
        if df.empty:
            return None, _u("\\uac00\\uaca9 \\ub370\\uc774\\ud130\\ub97c \\uac00\\uc838\\uc624\\uc9c0 \\ubabb\\ud588\\uc2b5\\ub2c8\\ub2e4.")

        close = df["Close"]
        current = float(close.iloc[-1])
        prev = float(close.iloc[-2])
        change = current - prev
        change_pct = (change / prev) * 100 if prev else 0.0

        rsi_val = float(_calc_rsi(close).iloc[-1])
        macd_line, signal_line, hist = _calc_macd(close)
        macd_v = float(macd_line.iloc[-1])
        sig_v = float(signal_line.iloc[-1])
        hist_v = float(hist.iloc[-1])
        upper, mid, lower = _calc_bollinger(close)

        lines = [
            f"[{company_name} ({ticker_code}) technical]",
            f"close={current:.2f}, change={change:+.2f} ({change_pct:+.2f}%)",
            f"RSI14={rsi_val:.2f}",
            f"MACD={macd_v:.4f}, SIGNAL={sig_v:.4f}, HIST={hist_v:.4f}",
            f"BB_UPPER={float(upper.iloc[-1]):.2f}, BB_MID={float(mid.iloc[-1]):.2f}, BB_LOWER={float(lower.iloc[-1]):.2f}",
            "Use only the values above. No investment advice.",
        ]
        return "\\n".join(lines), None
    except Exception as exc:
        return None, f"yfinance analysis error: {exc}"
