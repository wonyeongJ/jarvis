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


KOREAN_STOCK_MAP: dict[str, tuple[str, str]] = {
    "삼성전자": ("005930.KS", "삼성전자"),
    "삼성": ("005930.KS", "삼성전자"),
    "samsung": ("005930.KS", "삼성전자"),
    "에스케이하이닉스": ("000660.KS", "에스케이하이닉스"),
    "하이닉스": ("000660.KS", "에스케이하이닉스"),
    "네이버": ("035420.KS", "NAVER"),
    "naver": ("035420.KS", "NAVER"),
    "카카오": ("035720.KQ", "카카오"),
    "현대차": ("005380.KS", "현대차"),
    "기아": ("000270.KS", "기아"),
    "코스피": ("^KS11", "KOSPI"),
    "kospi": ("^KS11", "KOSPI"),
    "코스닥": ("^KQ11", "KOSDAQ"),
    "kosdaq": ("^KQ11", "KOSDAQ"),
    "애플": ("AAPL", "Apple"),
    "apple": ("AAPL", "Apple"),
    "aapl": ("AAPL", "Apple"),
    "엔비디아": ("NVDA", "NVIDIA"),
    "nvidia": ("NVDA", "NVIDIA"),
    "nvda": ("NVDA", "NVIDIA"),
    "테슬라": ("TSLA", "Tesla"),
    "tesla": ("TSLA", "Tesla"),
    "tsla": ("TSLA", "Tesla"),
    "마이크로소프트": ("MSFT", "Microsoft"),
    "microsoft": ("MSFT", "Microsoft"),
    "msft": ("MSFT", "Microsoft"),
}

ANALYSIS_ACTION_KEYWORDS = [
    "분석",
    "기술적 분석",
    "예측",
    "전략",
    "rsi",
    "macd",
    "볼린저밴드",
]

PRICE_ACTION_KEYWORDS = [
    "주가",
    "시세",
    "가격",
    "얼마",
    "현재가",
]

STOCK_CONTEXT_KEYWORDS = [
    "주식",
    "종목",
    "주가",
    "코스피",
    "코스닥",
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
        return None, "종목명을 인식하지 못했습니다. 예: '삼성전자 주가 알려줘'"

    try:
        df = yf.Ticker(ticker_code).history(period="5d", interval="1d")
        if df.empty:
            return None, "가격 데이터를 가져오지 못했습니다."

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
        return None, "종목명을 인식하지 못했습니다. 예: '삼성전자 주가 예상해줘'"

    try:
        df = yf.Ticker(ticker_code).history(period="3mo")
        if df.empty:
            return None, "가격 데이터를 가져오지 못했습니다."

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
