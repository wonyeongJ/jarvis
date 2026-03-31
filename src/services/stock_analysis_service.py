"""yfinance 기반 주식 기술적 분석 서비스 모듈.

사용자가 '예측', '분석', '기술적 분석' 등을 요청하면 이 모듈이 동작합니다.
yfinance로 실시간 OHLCV 데이터를 받아와 RSI, MACD, 볼린저밴드를 계산한 뒤,
LLM이 해석할 수 있는 텍스트 형태로 반환합니다.

⚠️ 이 모듈은 투자 조언을 하지 않습니다.
   계산된 기술적 지표를 근거로 한 현황 해석만 제공합니다.
"""
from __future__ import annotations

import re
from typing import Optional

# ─── 주요 한국 주식 종목명 → 야후파이낸스 티커 사전 ─────────────────────────
KOREAN_STOCK_MAP: dict[str, tuple[str, str]] = {
    # 이름: (티커코드, 공식명칭)
    "삼성전자": ("005930.KS", "삼성전자"),
    "삼성": ("005930.KS", "삼성전자"),
    "sk하이닉스": ("000660.KS", "SK하이닉스"),
    "하이닉스": ("000660.KS", "SK하이닉스"),
    "lg에너지솔루션": ("373220.KS", "LG에너지솔루션"),
    "카카오": ("035720.KQ", "카카오"),
    "카카오뱅크": ("323410.KS", "카카오뱅크"),
    "카카오페이": ("377300.KS", "카카오페이"),
    "네이버": ("035420.KS", "NAVER"),
    "naver": ("035420.KS", "NAVER"),
    "현대차": ("005380.KS", "현대자동차"),
    "현대자동차": ("005380.KS", "현대자동차"),
    "기아": ("000270.KS", "기아"),
    "기아차": ("000270.KS", "기아"),
    "포스코": ("005490.KS", "POSCO홀딩스"),
    "포스코홀딩스": ("005490.KS", "POSCO홀딩스"),
    "lg화학": ("051910.KS", "LG화학"),
    "셀트리온": ("068270.KS", "셀트리온"),
    "삼성바이오": ("207940.KS", "삼성바이오로직스"),
    "삼성바이오로직스": ("207940.KS", "삼성바이오로직스"),
    "kb금융": ("105560.KS", "KB금융"),
    "신한지주": ("055550.KS", "신한지주"),
    "하나지주": ("086790.KS", "하나금융지주"),
    "우리금융": ("316140.KS", "우리금융지주"),
    "kt": ("030200.KS", "KT"),
    "skt": ("017670.KS", "SK텔레콤"),
    "sk텔레콤": ("017670.KS", "SK텔레콤"),
    "lg전자": ("066570.KS", "LG전자"),
    "두산에너빌리티": ("034020.KS", "두산에너빌리티"),
    "한국전력": ("015760.KS", "한국전력"),
    "한화에어로스페이스": ("012450.KS", "한화에어로스페이스"),
    "한미반도체": ("042700.KS", "한미반도체"),
    "에코프로": ("086520.KQ", "에코프로"),
    "에코프로비엠": ("247540.KQ", "에코프로비엠"),
    # 지수
    "코스피": ("^KS11", "KOSPI"),
    "kospi": ("^KS11", "KOSPI"),
    "코스닥": ("^KQ11", "KOSDAQ"),
    "kosdaq": ("^KQ11", "KOSDAQ"),
    # 미국 빅테크 (달러 기준)
    "애플": ("AAPL", "Apple"),
    "apple": ("AAPL", "Apple"),
    "aapl": ("AAPL", "Apple"),
    "엔비디아": ("NVDA", "NVIDIA"),
    "nvidia": ("NVDA", "NVIDIA"),
    "nvda": ("NVDA", "NVIDIA"),
    "테슬라": ("TSLA", "Tesla"),
    "tesla": ("TSLA", "Tesla"),
    "마이크로소프트": ("MSFT", "Microsoft"),
    "구글": ("GOOGL", "Google(Alphabet)"),
    "메타": ("META", "Meta"),
}

# ─── 기술적 분석 질문 감지 키워드 ───────────────────────────────────────
# · 두 그룹 모두 포함되어야 True 로 판단합니다.
_ANALYSIS_ACTION_KEYWORDS = [
    "기술적 분석", "기술분석", "분석해줘", "분석해봐", "분석해",
    "예측해줘", "예측해봐", "예측해", "예상해줘", "예상해봐", "예상해",
    "전망해줘", "전망",
    "rsi", "macd", "볼린저", "이동평균", "차트 분석",
    "매수 신호", "매도 신호", "골든크로스", "데드크로스",
    "지표", "과매수", "과매도",
]

# 주식 맥락 확인용 키워드 — 이 중 하나 이상 있어야 주식 분석으로 인식
_STOCK_CONTEXT_KEYWORDS = [
    "주가", "주식", "종목", "코스피", "코스닥", "주", "우선주",
    "삼성", "스페트", "삼성전자", "하이닉스", "음성", "네이버", "컨테츠",
    "카카오", "현대차", "기아", "엔비디아", "테슬라", "애플", "엔비디아",
    "에코프로", "셀트리온", "포스코", "엔비디아", "메타", "마이크로소프트",
]


def is_stock_analysis_query(text: str) -> bool:
    """기술적 분석 요청 여부를 판단합니다.

    기술적 분석 액션 키워드(뺄 분석해줘, RSI 등)와
    주식 맥락 키워드(주가, 코스피, 삼성전자 등)가
    모두 포함되어야 True 를 반환합니다.
    날씨 예측처럼 주식 맥락 없이 단순히 '예측해줘'만 있는 쿼리는 False 를 반환합니다.
    """
    t = text.lower()
    has_action = any(k in t for k in _ANALYSIS_ACTION_KEYWORDS)
    # 주식 맥락: 직접 키워드 취합 OR 종목명 사전매칭
    has_stock_context = any(k in t for k in _STOCK_CONTEXT_KEYWORDS) or any(name in t for name in KOREAN_STOCK_MAP)
    return has_action and has_stock_context


def _resolve_ticker(query: str) -> tuple[Optional[str], Optional[str]]:
    """질문 텍스트에서 종목 이름을 찾아 티커와 공식명칭을 반환합니다."""
    q_lower = query.lower().replace(" ", "")
    for name, (ticker, official_name) in KOREAN_STOCK_MAP.items():
        if name.replace(" ", "") in q_lower:
            return ticker, official_name
    return None, None


def _calc_rsi(close, period: int = 14):
    """RSI(상대강도지수)를 계산합니다."""
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window=period).mean()
    loss = (-delta.clip(upper=0)).rolling(window=period).mean()
    rs = gain / loss.replace(0, float("inf"))
    return 100 - (100 / (1 + rs))


def _calc_macd(close, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD 라인, 시그널 라인, 히스토그램을 계산합니다."""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line, macd_line - signal_line


def _calc_bollinger(close, period: int = 20, std_mult: float = 2.0):
    """볼린저밴드 상단/중간(SMA)/하단을 계산합니다."""
    sma = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    return sma + std_mult * std, sma, sma - std_mult * std


def run_technical_analysis(query: str) -> tuple[Optional[str], Optional[str]]:
    """주식 기술적 분석을 수행하고 LLM에 전달할 텍스트를 반환합니다.

    Returns:
        (analysis_text, error_message) — 성공 시 error는 None, 실패 시 text는 None.
    """
    try:
        import yfinance as yf  # noqa: PLC0415
    except ImportError:
        return None, (
            "`yfinance` 패키지가 설치되지 않았습니다.\n"
            "가상환경에서 `pip install yfinance` 를 실행한 뒤 재시작해 주세요."
        )

    ticker_code, company_name = _resolve_ticker(query)
    if not ticker_code:
        return None, (
            "종목명을 인식하지 못했습니다.\n"
            "예) '삼성전자 기술적 분석해줘', '네이버 RSI 알려줘'"
        )

    try:
        df = yf.Ticker(ticker_code).history(period="3mo")
        if df.empty:
            return None, f"'{company_name}' 가격 데이터를 가져오지 못했습니다. 티커({ticker_code})를 확인해 주세요."

        close = df["Close"]
        is_usd = ticker_code in {"AAPL", "NVDA", "TSLA", "MSFT", "GOOGL", "META"}
        currency = "USD" if is_usd else "원"
        price_fmt = lambda p: f"${p:,.2f}" if is_usd else f"{p:,.0f}원"  # noqa: E731

        current = close.iloc[-1]
        prev = close.iloc[-2]
        change = current - prev
        change_pct = (change / prev) * 100

        # ── 기술 지표 계산 ────────────────────────────────────────────────────
        rsi_val = _calc_rsi(close).iloc[-1]
        macd_line, signal_line, histogram = _calc_macd(close)
        macd_v, sig_v, hist_v = macd_line.iloc[-1], signal_line.iloc[-1], histogram.iloc[-1]
        upper_bb, mid_bb, lower_bb = _calc_bollinger(close)
        upper_v, mid_v, lower_v = upper_bb.iloc[-1], mid_bb.iloc[-1], lower_bb.iloc[-1]

        ma5 = close.rolling(5).mean().iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
        ma60 = close.rolling(60).mean().iloc[-1] if len(close) >= 60 else None

        avg_vol = df["Volume"].rolling(20).mean().iloc[-1]
        today_vol = df["Volume"].iloc[-1]
        vol_ratio = today_vol / avg_vol if avg_vol > 0 else 0

        # ── RSI 해석 ─────────────────────────────────────────────────────────
        if rsi_val > 70:
            rsi_interp = f"⚠️  과매수 구간 ({rsi_val:.1f}) — 단기 차익실현 매물 가능성"
        elif rsi_val < 30:
            rsi_interp = f"⚠️  과매도 구간 ({rsi_val:.1f}) — 기술적 반등 가능성"
        else:
            rsi_interp = f"중립 ({rsi_val:.1f}) — 추세 지속 가능성"

        # ── MACD 해석 ─────────────────────────────────────────────────────────
        if macd_v > sig_v and hist_v > 0:
            macd_interp = "골든크로스 유지 (상승 모멘텀)"
        elif macd_v < sig_v and hist_v < 0:
            macd_interp = "데드크로스 유지 (하락 모멘텀)"
        elif macd_v > sig_v and hist_v <= 0:
            macd_interp = "골든크로스 진입 직전 (상승 전환 신호)"
        else:
            macd_interp = "데드크로스 진입 직전 (하락 전환 신호)"

        # ── 볼린저밴드 해석 ───────────────────────────────────────────────────
        if current > upper_v:
            bb_interp = "상단 밴드 돌파 — 강한 상승세, 과열 주의"
        elif current < lower_v:
            bb_interp = "하단 밴드 이탈 — 강한 하락세, 반등 가능성"
        else:
            bb_pos_pct = (current - lower_v) / (upper_v - lower_v) * 100 if (upper_v - lower_v) > 0 else 50
            bb_interp = f"밴드 내 위치 (하단 대비 {bb_pos_pct:.0f}% 지점)"

        # ── MA 해석 (정배열/역배열) ───────────────────────────────────────────
        if ma5 > ma20 and (ma60 is None or ma20 > ma60):
            ma_interp = "정배열 (단기 > 중기 > 장기) — 상승 추세"
        elif ma5 < ma20 and (ma60 is None or ma20 < ma60):
            ma_interp = "역배열 (단기 < 중기 < 장기) — 하락 추세"
        else:
            ma_interp = "이동평균 혼조 — 추세 전환 구간 가능성"

        # ── 최종 텍스트 조립 ──────────────────────────────────────────────────
        lines = [
            f"[{company_name} ({ticker_code}) 기술적 분석 데이터]",
            f"📌 현재가: {price_fmt(current)}  ({change:+.2f} / {change_pct:+.2f}%)",
            "",
            f"📊 이동평균 → {ma_interp}",
            f"  MA5={price_fmt(ma5)}  /  MA20={price_fmt(ma20)}"
            + (f"  /  MA60={price_fmt(ma60)}" if ma60 else ""),
            "",
            f"📊 RSI(14): {rsi_interp}",
            "",
            f"📊 MACD(12,26,9): {macd_interp}",
            f"  MACD={macd_v:+.2f}  /  시그널={sig_v:+.2f}  /  히스토그램={hist_v:+.2f}",
            "",
            f"📊 볼린저밴드(20, 2σ): {bb_interp}",
            f"  상단={price_fmt(upper_v)}  /  중간={price_fmt(mid_v)}  /  하단={price_fmt(lower_v)}",
            "",
            f"📊 거래량: 오늘 {today_vol:,.0f}주  (20일 평균 대비 {vol_ratio:.1f}배)",
            "",
            "※ 위 데이터는 기술적 지표이며 투자 조언이 아닙니다.",
        ]
        return "\n".join(lines), None

    except Exception as exc:
        return None, f"기술적 분석 처리 중 오류 발생: {exc}"
