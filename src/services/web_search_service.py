"""간단한 웹 검색과 웹 검색 필요 여부 판단을 담당하는 서비스 모듈입니다."""

from __future__ import annotations

import requests

from core.settings import get_env


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


def search_naver_direct(query):
    """네이버 모바일 검색 결과를 직접 스크래핑하여 실시간 날씨, 주가 등 위젯 텍스트를 최우선으로 추출합니다."""
    try:
        import urllib.request
        import urllib.parse
        from bs4 import BeautifulSoup

        url = f"https://m.search.naver.com/search.naver?query={urllib.parse.quote(query)}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        )
        html = urllib.request.urlopen(req, timeout=5).read().decode("utf-8", errors="ignore")
        soup = BeautifulSoup(html, "lxml")

        # 불필요한 태그 제거 (스크립트, 스타일, 헤더, 푸터, 네비게이션, 광고 등)
        for tag in soup(["script", "style", "header", "footer", "nav", "noscript", "svg", "button", "img"]):
            tag.decompose()

        # 모바일 검색은 주로 #ct 하위에 핵심 정보 렌더링
        main_content = soup.find(id="ct") or soup.body or soup
        text = main_content.get_text(separator=" ", strip=True)
        text = " ".join(text.split())

        snippet = text[:1500] if len(text) > 1500 else text
        if not snippet or len(snippet) < 20:
            return None, "네이버 스크래핑 파싱 실패: 데이터가 부족합니다."

        return f"[네이버 실시간 검색 화면 요약]\n출처 URL: {url}\n내용: {snippet}", None
    except Exception as error:
        return None, f"네이버 스크래핑 오류: {error}"


import datetime

def web_search_with_status(query, max_results=3):
    """네이버 실시간 스크래핑 우선 후, 실패하면 일반 전역 검색을 수행합니다."""
    # 0단계: 네이버 실시간 직접 스크래핑 (날씨, 증권 카드를 모바일에서 파싱)
    naver_result, naver_error = search_naver_direct(query)
    if naver_result:
        return {"content": naver_result, "provider": "naver_scraping", "errors": []}

    # 실시간/최신 정보가 필요한 경우 강제로 오늘 날짜를 쿼리에 주입하여 낡은 검색 결과를 필터링
    fresh_keywords = ["날씨", "주가", "주식", "환율", "현재", "오늘", "내일", "시세", "뉴스", "최신", "기온", "날짜"]
    if any(k in query for k in fresh_keywords):
        now_str = datetime.datetime.now().strftime("%Y년 %m월 %d일")
        query = f"{now_str} {query}"

    kr_domains = ["naver.com", "tistory.com", "daum.net", "chosun.com", "mk.co.kr", "hankyung.com", "yna.co.kr"]
    
    # 1단계: 국내 메인 도메인(네이버 등) 한정 검색
    tavily_result_kr, error_kr = search_tavily(query, max_results, kr_domains)
    if tavily_result_kr:
        return {"content": tavily_result_kr, "provider": "tavily (Korean Domains)", "errors": []}

    # 2단계: 글로벌 Tavily 검색 (1단계로 충분한 정보가 안 나오면 구글 등 전 세계 검색)
    tavily_result_gl, error_gl = search_tavily(query, max_results)
    if tavily_result_gl:
        return {"content": tavily_result_gl, "provider": "tavily (Global)", "errors": [error_kr] if error_kr else []}

    # 3단계: DuckDuckGo 한국어 지역 검색
    duckduckgo_result, duckduckgo_error = search_duckduckgo(query, max_results)
    if duckduckgo_result:
        errors = [error_kr, error_gl]
        return {"content": duckduckgo_result, "provider": "duckduckgo (kr-kr)", "errors": [e for e in errors if e]}

    errors = [e for e in [error_kr, error_gl, duckduckgo_error] if e]
    return {"content": None, "provider": None, "errors": errors}


def web_search(query, max_results=3):
    """Tavily 를 우선 사용하고 실패하면 DuckDuckGo 로 대체합니다."""
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
        "주가",
        "주식",
        "환율",
        "뉴스",
        "최신",
        "오늘",
        "현재",
        "지금",
        "요약",
        "최근",
        "얼마야",
        "얼마예요",
        "얼마지",
        "얼마",
        "날씨",
        "기온",
        "결과",
        "정보",
        "검색해줘",
        "찾아줘",
    ]
    return any(keyword in normalized for keyword in search_keywords)
