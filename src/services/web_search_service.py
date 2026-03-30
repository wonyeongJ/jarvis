"""간단한 웹 검색과 웹 검색 필요 여부 판단을 담당하는 서비스 모듈입니다."""

from __future__ import annotations

import datetime
import re
import requests

from core.settings import get_env


# ---------------------------------------------------------------------------
# 검색어 유형별 실제 데이터 포함 여부를 검증하는 패턴 목록.
# 네이버 스크래핑 결과가 JS 미렌더링으로 껍데기만 왔을 때를 걸러냅니다.
# ---------------------------------------------------------------------------
_QUERY_VALIDATORS = [
    # 날씨/기온 질문 → 숫자+°C 또는 숫자+도 가 있어야 유효
    (["날씨", "기온", "온도"], r"\d+(\.\d+)?\s*(°C|℃|도)"),
    # 주가/환율 질문 → 숫자+원 또는 콤마 포함 숫자 가 있어야 유효
    (["주가", "주식", "환율", "시세"], r"\d{1,3}(,\d{3})+|\d+(\.\d+)?\s*원"),
]


def _is_scraping_result_valid(query: str, snippet: str) -> bool:
    """스크래핑 결과에 질문 유형에 맞는 실제 데이터가 있는지 검증합니다.

    검증 대상 질문 유형(날씨·주가 등)이면 패턴 매칭으로 확인하고,
    그 외 질문은 길이(100자 이상)로만 판단합니다.
    """
    for keywords, pattern in _QUERY_VALIDATORS:
        if any(k in query for k in keywords):
            return bool(re.search(pattern, snippet))
    # 검증 패턴이 없는 일반 질문은 내용이 충분히 길면 유효로 판단
    return len(snippet) >= 100


def search_tavily(query, max_results=2, domains=None):
    """Tavily 검색 결과와 실패 사유를 함께 반환합니다."""
    tavily_api_key = get_env("TAVILY_API_KEY")
    if not tavily_api_key:
        return None, "TAVILY_API_KEY 가 설정되지 않았습니다."

    try:
        payload = {
            "api_key": tavily_api_key,
            "query": query,
            "max_results": max_results,
            "include_answer": True,
            "search_depth": "basic",
        }
        if domains:
            payload["include_domains"] = domains

        response = requests.post(
            "https://api.tavily.com/search",
            json=payload,
            timeout=6,
        )
        if response.status_code == 401:
            return None, "Tavily 인증에 실패했습니다. API 키를 확인해 주세요."
        if response.status_code == 403:
            return None, "Tavily 요청이 거부되었습니다."
        if response.status_code == 429:
            return None, "Tavily 요청 한도를 초과했습니다."
        if response.status_code >= 400:
            return None, f"Tavily HTTP {response.status_code} 오류가 발생했습니다."

        data = response.json()
        contents = []
        if data.get("answer"):
            contents.append(f"[AI 요약]\n{data['answer']}")
        for result in data.get("results", []):
            contents.append(
                f"[제목: {result.get('title', '')}]\n"
                f"[출처: {result.get('url', '')}]\n"
                f"{result.get('content', '')}"
            )

        if not contents:
            return None, "Tavily 검색 결과가 비어 있습니다."
        return "\n\n---\n\n".join(contents), None
    except requests.Timeout:
        return None, "Tavily 요청이 시간 초과되었습니다."
    except requests.RequestException as error:
        return None, f"Tavily 네트워크 오류: {error}"
    except Exception as error:
        return None, f"Tavily 처리 오류: {error}"


def search_duckduckgo(query, max_results=3):
    """DuckDuckGo 검색 결과와 실패 사유를 함께 반환합니다."""
    try:
        from ddgs import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(query, region="kr-kr", max_results=max_results))
        if not results:
            return None, "DuckDuckGo 검색 결과가 비어 있습니다."
        contents = [
            f"[제목: {result.get('title', '')}]\n"
            f"[출처: {result.get('href', '')}]\n"
            f"{result.get('body', '')}"
            for result in results
        ]
        return "\n\n---\n\n".join(contents), None
    except Exception as error:
        return None, f"DuckDuckGo 검색 실패: {error}"


def _scrape_naver_weather_widget(soup):
    """네이버 모바일 날씨 위젯을 CSS 선택자로 직접 집중 추출합니다.

    일반 텍스트 추출보다 훨씬 정확하게 날씨 카드 영역만 골라냅니다.
    """
    # 네이버 모바일 날씨 카드에서 주로 사용되는 클래스/섹션 후보 (우선순위 순)
    selector_groups = [
        "div[class*='weather']",
        "section[class*='weather']",
        "div[class*='Weather']",
        "div[class*='temperature']",
        "div[class*='today']",
        "div[class*='forecast']",
        "div[class*='climate']",
        "div[class*='finedust']",  # 미세먼지
    ]

    seen = set()
    texts = []
    for selector in selector_groups:
        for el in soup.select(selector):
            t = el.get_text(separator=" ", strip=True)
            t = " ".join(t.split())
            if t and len(t) > 10 and t not in seen:
                seen.add(t)
                texts.append(t)

    if texts:
        combined = " | ".join(texts)
        return combined[:2500]
    return None


def _build_weather_query(query):
    """날씨 질문에서 지역명을 추출해 네이버 검색에 최적화된 쿼리를 반환합니다.

    예) '세종 날씨 알려줘' → '세종 현재 날씨 기온'
    """
    # 날씨 관련 조사/동사/시제 표현 제거 후 지역명만 남김
    clean = re.sub(
        r"알려줘|가르쳐|어때|어떠|어떤지|어떻게|날씨|기온|온도|현재|지금|오늘|내일|요즘|이번주|주간",
        "",
        query,
    ).strip()
    region = clean if clean else ""
    if region:
        return f"{region} 현재 날씨 기온"
    return "오늘 날씨 현재 기온"


def search_naver_direct(query):
    """네이버 모바일 검색 결과를 직접 스크래핑하여 실시간 날씨, 주가 등 위젯 텍스트를 추출합니다.

    날씨 쿼리의 경우:
    1) _build_weather_query()로 네이버 최적화 쿼리를 생성합니다.
    2) _scrape_naver_weather_widget()으로 날씨 위젯 영역을 직접 집중 추출합니다.
    3) 위젯 추출 실패 시 일반 텍스트(3000자)로 확대 탐색합니다.
    """
    is_weather_query = any(k in query for k in ["날씨", "기온", "온도"])

    try:
        import urllib.request
        import urllib.parse
        from bs4 import BeautifulSoup

        # ★ 날씨 쿼리일 때 Naver에 최적화된 쿼리 사용 (지역 + 날씨 + 기온)
        naver_query = _build_weather_query(query) if is_weather_query else query

        url = f"https://m.search.naver.com/search.naver?query={urllib.parse.quote(naver_query)}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            },
        )
        html = urllib.request.urlopen(req, timeout=5).read().decode("utf-8", errors="ignore")
        soup = BeautifulSoup(html, "lxml")

        # 불필요한 태그 제거
        for tag in soup(["script", "style", "header", "footer", "nav", "noscript", "svg", "button", "img"]):
            tag.decompose()

        # ★ 날씨 쿼리: CSS 선택자로 위젯 영역만 집중 추출
        if is_weather_query:
            widget_text = _scrape_naver_weather_widget(soup)
            if widget_text and _is_scraping_result_valid(query, widget_text):
                return f"[네이버 날씨 위젯 직접 추출]\n출처 URL: {url}\n내용: {widget_text}", None
            # 위젯 실패 시 일반 텍스트 3000자로 확대 탐색
            main_content = soup.find(id="ct") or soup.body or soup
            text = " ".join(main_content.get_text(separator=" ", strip=True).split())
            snippet = text[:3000] if len(text) > 3000 else text
        else:
            # 주가 등 일반 쿼리는 기존 방식 유지
            main_content = soup.find(id="ct") or soup.body or soup
            text = " ".join(main_content.get_text(separator=" ", strip=True).split())
            snippet = text[:1500] if len(text) > 1500 else text

        if not snippet or len(snippet) < 20:
            return None, "네이버 스크래핑 파싱 실패: 데이터가 부족합니다."

        if not _is_scraping_result_valid(query, snippet):
            return None, "네이버 스크래핑: 질문에 맞는 실제 데이터를 찾지 못했습니다. (JS 미렌더링 가능성)"

        return f"[네이버 실시간 검색 화면 요약]\n출처 URL: {url}\n내용: {snippet}", None
    except Exception as error:
        return None, f"네이버 스크래핑 오류: {error}"


def web_search_with_status(query, max_results=3):
    """검색 소스를 순차적으로 시도하여 유효한 결과를 반환합니다.

    [검색 순서]
    0단계: 네이버 모바일 직접 스크래핑 (실시간 날씨·주가 카드 우선)
           → 데이터 검증 실패 시 다음 단계로 자동 이동
    1단계: Tavily - 국내 주요 도메인 한정 (naver, daum, 언론사 등)
    2단계: Tavily - 글로벌 전체 검색
    3단계: DuckDuckGo - 한국어 지역 검색 (kr-kr)
    """
    collected_errors = []

    # 0단계: 네이버 모바일 직접 스크래핑
    naver_result, naver_error = search_naver_direct(query)
    if naver_result:
        return {"content": naver_result, "provider": "naver_scraping", "errors": []}
    # 검증 실패 시 오류를 기록하고 다음 단계로 진행
    collected_errors.append(f"[0단계 네이버 스크래핑] {naver_error}")

    # 실시간 키워드가 포함된 경우 쿼리를 정제하고 오늘 날짜를 주입하여 최신 결과를 유도.
    # 단, "지금" / "현재" 같은 시간 표현은 검색엔진에 불필요하므로 제거한 뒤 날짜를 붙입니다.
    fresh_keywords = ["날씨", "주가", "주식", "환율", "현재", "오늘", "내일", "지금", "시세", "뉴스", "최신", "기온", "날짜"]
    enriched_query = query
    if any(k in query for k in fresh_keywords):
        now_str = datetime.datetime.now().strftime("%Y년 %m월 %d일")
        # 자연어 시간 표현 제거 후 날짜 조건을 뒤에 붙여 검색 정확도를 높임
        clean_query = re.sub(r"지금|현재|오늘|", "", query).strip()
        enriched_query = f"{clean_query} {now_str}"

    # 1단계: Tavily - 국내 주요 도메인 한정
    kr_domains = ["naver.com", "weather.go.kr", "kma.go.kr", "daum.net", "chosun.com", "mk.co.kr", "hankyung.com", "yna.co.kr"]
    tavily_result_kr, error_kr = search_tavily(enriched_query, max_results, kr_domains)
    if tavily_result_kr:
        return {"content": tavily_result_kr, "provider": "tavily (Korean Domains)", "errors": collected_errors}
    collected_errors.append(f"[1단계 Tavily KR] {error_kr}")

    # 2단계: Tavily - 글로벌 전체 검색
    tavily_result_gl, error_gl = search_tavily(enriched_query, max_results)
    if tavily_result_gl:
        return {"content": tavily_result_gl, "provider": "tavily (Global)", "errors": collected_errors}
    collected_errors.append(f"[2단계 Tavily Global] {error_gl}")

    # 3단계: DuckDuckGo - 한국어 지역 검색
    duckduckgo_result, duckduckgo_error = search_duckduckgo(enriched_query, max_results)
    if duckduckgo_result:
        return {"content": duckduckgo_result, "provider": "duckduckgo (kr-kr)", "errors": collected_errors}
    collected_errors.append(f"[3단계 DuckDuckGo] {duckduckgo_error}")

    # 모든 단계 실패
    return {"content": None, "provider": None, "errors": collected_errors}


def web_search(query, max_results=3):
    """web_search_with_status 의 content 만 반환하는 편의 함수입니다."""
    return web_search_with_status(query, max_results).get("content")


def should_use_web_search(text):
    """입력이 최신 정보가 필요한 검색성 질문인지 판단합니다."""
    normalized = text.strip()
    if len(normalized) < 5:
        return False

    no_search_exact = {"헤이", "hi", "hello", "안녕", "응", "그래", "네", "아니", "맞아", "고마워", "좋네"}
    no_search_starts = ["안녕", "고마워", "감사", "수고", "좋아", "오케", "그리고", "대박", "응", "네"]
    if normalized.lower() in no_search_exact or any(normalized.startswith(keyword) for keyword in no_search_starts):
        return False

    search_keywords = [
        "주가", "주식", "환율", "뉴스", "최신", "오늘", "현재", "지금",
        "요약", "최근", "얼마야", "얼마예요", "얼마지", "얼마",
        "날씨", "기온", "결과", "정보", "검색해줘", "찾아줘",
    ]
    return any(keyword in normalized for keyword in search_keywords)