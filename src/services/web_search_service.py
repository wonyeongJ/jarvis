"""간단한 웹 검색과 웹 검색 필요 여부 판단을 담당하는 서비스 모듈입니다."""

from __future__ import annotations

import datetime
import html as html_lib
import re
import requests

from core.settings import get_env
from services.forecast_service import get_tomorrow_forecast_from_open_meteo


# ---------------------------------------------------------------------------
# 검색어 유형별 실제 데이터 포함 여부를 검증하는 패턴 목록.
# 네이버 스크래핑 결과가 JS 미렌더링으로 껍데기만 왔을 때를 걸러냅니다.
# ---------------------------------------------------------------------------
_QUERY_VALIDATORS = [
    # 날씨/기온 질문 → 숫자+단위 또는 날씨 상태 키워드(맑음, 흐림, 비, 눈 등)가 있으면 유효
    (["날씨", "기온", "온도"], r"\d+(\.\d+)?\s*(°C|℃|도|°)|맑음|흐림|구름|비|눈"),
    # 주가/환율 질문 → 숫자+원 또는 콤마 포함 숫자 가 있어야 유효
    (["주가", "주식", "환율", "시세"], r"\d{1,3}(,\d{3})+|\d+(\.\d+)?\s*원"),
]

_FORECAST_KEYWORDS = ["내일", "모레", "주간", "이번주", "다음주", "주말", "예보", "시간별", "내일날씨"]


def _is_forecast_weather_query(query: str) -> bool:
    """날씨 질문 중에서도 '예보/미래' 요청인지 판단합니다."""
    normalized = (query or "").replace(" ", "")
    return any(k.replace(" ", "") in normalized for k in _FORECAST_KEYWORDS)


def _is_weather_query_text(query: str) -> bool:
    """'날씨' 단어가 없어도 예보 키워드면 날씨 질의로 취급합니다."""
    q = query or ""
    return any(k in q for k in ["날씨", "기온", "온도"]) or _is_forecast_weather_query(q)


def _extract_weather_location_tokens(query: str) -> list[str]:
    """날씨 검색어에서 지역 토큰을 대략 추출합니다. (예: '세종 고운동 내일 날씨' -> ['세종', '고운동'])"""
    if not query:
        return []
    normalized = re.sub(r"\s+", " ", query).strip()
    # 시간/날씨 관련 단어 제거
    normalized = re.sub(r"(내일|모레|오늘|지금|현재|주간|이번주|다음주|주말|예보|시간별)", " ", normalized)
    normalized = re.sub(r"(날씨|기온|온도)", " ", normalized)
    tokens = [t for t in normalized.split(" ") if t]
    # 너무 짧은 토큰은 제외
    tokens = [t for t in tokens if len(t) >= 2]
    return tokens[:2]


def _extract_forecast_snippet_from_html(html: str, location_tokens: list[str]) -> str | None:
    """예보(내일/시간별/최저·최고 등) 텍스트가 HTML에 존재할 때, 관련 구간을 짧게 추출합니다."""
    if not html:
        return None
    text = _clean_html_text(html)
    if location_tokens and not any(tok in text for tok in location_tokens):
        return None
    # 예보 단서가 있는 경우에만 반환
    forecast_markers = ["내일", "모레", "오전", "오후", "시간별", "최저", "최고", "강수", "확률"]
    if not any(m in text for m in forecast_markers):
        return None
    # 온도/강수처럼 숫자 단서도 같이 있으면 더 신뢰
    has_numbers = bool(re.search(r"\d+(\.\d+)?\s*(°C|℃|도|°|mm|%)", text))
    if not has_numbers:
        # 숫자가 전혀 없으면 예보 정보로 쓰기 애매
        return None

    # 단순 "네이버 검색" 같은 UI 문구만 잡히는 경우를 방지하기 위해,
    # 날씨 상태 단서(맑음/흐림/비/눈 등) 또는 최저·최고 표식이 실제로 포함되어야 합니다.
    weather_state_markers = ["맑음", "흐림", "구름", "비", "눈", "소나기", "천둥", "번개", "미세먼지"]
    has_weather_state = any(m in text for m in weather_state_markers)
    has_minmax = ("최저" in text) or ("최고" in text)
    if not (has_weather_state or has_minmax):
        return None

    # '내일' 주변을 우선으로 잘라냅니다.
    idx = text.find("내일")
    if idx == -1:
        # 다른 마커라도 있는 곳을 기준으로 잘라냄
        for m in forecast_markers:
            idx = text.find(m)
            if idx != -1:
                break
    if idx == -1:
        return None

    start = max(0, idx - 200)
    end = min(len(text), idx + 600)
    snippet = text[start:end].strip()
    snippet = " ".join(snippet.split())
    if not snippet:
        return None
    # 잘라낸 스니펫에도 예보 단서 + 수치 단서가 실제로 들어있는지 재검증
    if not any(m in snippet for m in forecast_markers):
        return None
    if not re.search(r"\d+(\.\d+)?\s*(°C|℃|도|°|mm|%)", snippet):
        return None
    # UI 잡음 제거: "네이버 검색"만 남는 경우 차단
    if "네이버 검색" in snippet and not (any(m in snippet for m in weather_state_markers) or ("최저" in snippet) or ("최고" in snippet)):
        return None
    return snippet[:1200]

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


def _clean_html_text(fragment: str) -> str:
    """Strip HTML tags and normalize whitespace."""
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = html_lib.unescape(text)
    return " ".join(text.split())


def _extract_naver_weather_from_html(html: str) -> dict[str, str] | None:
    """네이버 모바일 날씨 카드 HTML에서 필드별 데이터를 추출합니다."""
    # 날씨 카드를 나타내는 핵심 클래스 확인
    if "temperature_text" not in html and "weather_info" not in html:
        return None

    data: dict[str, str] = {}

    # 1. 위치 정보 추출
    location_match = re.search(r'<span class="select_txt">(.*?)</span>', html)
    basis_match = re.search(r'<span class="select_txt_sub">(.*?)</span>', html)
    if location_match:
        data["location"] = _clean_html_text(location_match.group(1))
    if basis_match:
        data["basis"] = _clean_html_text(basis_match.group(1))

    # 2. 온도 추출 (여러 패턴 대응)
    # 패턴 A: blind 현재 온도 텍스트 뒤의 수치
    temp_match = re.search(r'현재 온도</span>([0-9.-]+)', html)
    if not temp_match:
        # 패턴 B: temperature_text 클래스 내부의 strong 태그
        temp_match = re.search(r'class="temperature_text".*?>([0-9.-]+)<span>°', html, re.DOTALL)
    if not temp_match:
        # 패턴 C: 단순 숫자+° 패키지 소스에서 찾기
        temp_match = re.search(r'([0-9.-]+)°', html)
    
    if temp_match:
        data["temp"] = temp_match.group(1) + "°"
    else:
        return None

    # 3. 날씨 상태 (맑음, 흐림 등)
    weather_match = re.search(r'<span class="weather before_slash">(.*?)</span>', html)
    if not weather_match:
        weather_match = re.search(r'<span class="weather">(.*?)</span>', html)
    if weather_match:
        data["weather"] = _clean_html_text(weather_match.group(1))

    # 4. 요약 문구 (어제보다... 변동폭 포함)
    summary_match = re.search(r'<p class="summary">(.*?)</p>', html, re.DOTALL)
    if summary_match:
        data["summary"] = _clean_html_text(summary_match.group(1))

    # 5. 상세 정보 (체감, 습도, 바람)
    details_text = _clean_html_text(html)
    feels_like_match = re.search(r'체감\s*([0-9.-]+°)', details_text)
    humidity_match = re.search(r'습도\s*([0-9]+%)', details_text)
    wind_match = re.search(r'([남북동서]풍\s*[0-9.-]+m/s)', details_text)
    
    if feels_like_match:
        data["feels_like"] = feels_like_match.group(1)
    if humidity_match:
        data["humidity"] = humidity_match.group(1)
    if wind_match:
        data["wind"] = wind_match.group(1)

    # 6. 대기질 정보
    report_card_area = re.search(r'<div class="report_card_wrap">(.*?)</ul>', html, re.DOTALL)
    if report_card_area:
        report_html = report_card_area.group(1)
        cards = re.findall(r'<li class="item_?[\w]*">.*?<strong class="item_title">(.*?)</strong>\s*<span class="item_status.*?">(.*?)</span>', report_html, re.DOTALL)
        for title_html, status_html in cards:
            title = _clean_html_text(title_html)
            status = _clean_html_text(status_html)
            if "미세먼지" in title and "초" not in title:
                data["dust"] = status
            elif "초미세먼지" in title:
                data["ultrafine_dust"] = status
            elif "자외선" in title:
                data["uv"] = status

    return data


def _format_naver_weather_result(data: dict[str, str], url: str) -> str:
    """Serialize structured weather data for the chat worker."""
    ordered_keys = [
        "location",
        "basis",
        "temp",
        "weather",
        "summary",
        "feels_like",
        "humidity",
        "wind",
        "dust",
        "ultrafine_dust",
        "uv",
    ]
    lines = ["[NAVER_WEATHER]", f"url={url}"]
    for key in ordered_keys:
        value = data.get(key)
        if value:
            lines.append(f"{key}={value}")
    return "\n".join(lines)


def _scrape_naver_weather_widget(soup):
    """BeautifulSoup-based fallback extractor."""
    selector_groups = [
        "section.cs_weather_new",
        "section[class*='weather']",
        "div.weather_info",
        "div[class*='weather']",
        "div[class*='temperature']",
        "div[class*='today']",
        "div[class*='forecast']",
        "div[class*='finedust']",
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
        return " | ".join(texts)[:2500]
    return None


def _build_weather_queries(query):
    """지정된 지역의 날씨 검색을 위한 쿼리 목록을 만듭니다.
    네이버 실시간 날씨 카드를 호출하기 위해 최적화된 키워드를 사용합니다.
    """
    # base query에 이미 '날씨/기온/현재' 등이 붙어 있으면 중복으로 더 붙지 않게 정리
    base = re.sub(r"\s+", " ", (query or "").strip())
    base = re.sub(r"(현재\s*)?(날씨|기온|온도)\s*$", "", base).strip()
    is_forecast = _is_forecast_weather_query(query)
    if is_forecast:
        candidates = [
            f"{base} 내일 날씨",
            f"{base} 내일 기온",
            f"{base} 시간별 날씨",
            f"{base} 예보",
            f"{base} 주간 날씨",
        ]
    else:
        candidates = [
            f"{base} 날씨",
            f"{base} 현재 날씨",
            f"{base} 현재 기온",
            "오늘 날씨 현재 기온",
        ]
    
    deduped = []
    seen = set()
    for candidate in candidates:
        normalized = re.sub(r"\s+", " ", candidate).strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return deduped

    return deduped


def search_naver_direct(query):
    """Scrape Naver mobile search results for weather or stock widgets."""
    is_weather_query = _is_weather_query_text(query)
    is_forecast_weather = _is_forecast_weather_query(query) if is_weather_query else False
    location_tokens = _extract_weather_location_tokens(query) if is_weather_query else []

    try:
        import urllib.parse
        import urllib.request

        candidate_queries = _build_weather_queries(query) if is_weather_query else [query]
        last_error = None
        forecast_markers = ["내일", "모레", "주간", "이번주", "다음주", "주말", "예보", "시간별", "오전", "오후", "최저", "최고", "강수"]

        for naver_query in candidate_queries:
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

            # 예보 질의는 위젯 셀렉터가 놓치는 경우가 있어, HTML 전체 텍스트에서 예보 스니펫을 먼저 시도합니다.
            if is_weather_query and is_forecast_weather:
                forecast_snippet = _extract_forecast_snippet_from_html(html, location_tokens)
                if forecast_snippet:
                    return f"[NAVER_SNIPPET]\nurl={url}\ncontent={forecast_snippet}", None

            # 예보(내일/주간 등) 질의는 '현재 온도' 카드 파싱([NAVER_WEATHER])을 타면 잘못된 직답이 나오기 쉽습니다.
            # 따라서 예보 질의는 현재 카드 파싱을 건너뛰고, 예보 텍스트가 포함된 위젯/스니펫만 사용합니다.
            if is_weather_query and not is_forecast_weather:
                weather_data = _extract_naver_weather_from_html(html)
                if weather_data:
                    return _format_naver_weather_result(weather_data, url), None

            try:
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(html, "lxml")
                for tag in soup(["script", "style", "header", "footer", "nav", "noscript", "svg", "button", "img"]):
                    tag.decompose()

                if is_weather_query:
                    widget_text = _scrape_naver_weather_widget(soup)
                    if widget_text:
                        # 지역이 섞여 들어오는 경우(세종 질문인데 서울 위젯 등)를 거르기 위해
                        # 질의에서 추출한 지역 토큰이 위젯 텍스트에 포함되는 경우만 채택합니다.
                        if location_tokens and not any(token in widget_text for token in location_tokens):
                            continue
                        if is_forecast_weather:
                            # '내일/모레/주간/예보/시간별' 같은 단서가 실제로 포함되어야 예보로 인정
                            has_marker = any(m in widget_text for m in forecast_markers)
                            has_temp = bool(re.search(r"\d+(\.\d+)?\s*(°C|℃|도|°)", widget_text))
                            if has_marker and (has_temp or _is_scraping_result_valid(query, widget_text)):
                                return f"[NAVER_SNIPPET]\nurl={url}\ncontent={widget_text}", None
                        elif _is_scraping_result_valid(query, widget_text):
                            return f"[NAVER_SNIPPET]\nurl={url}\ncontent={widget_text}", None

                main_content = soup.find(id="ct") or soup.body or soup
                text = " ".join(main_content.get_text(separator=" ", strip=True).split())
            except Exception:
                text = _clean_html_text(html)

            snippet_limit = 3000 if is_weather_query else 1500
            snippet = text[:snippet_limit] if len(text) > snippet_limit else text

            if not snippet or len(snippet) < 20:
                last_error = "네이버 스크래핑 파싱 실패: 데이터가 부족합니다."
                continue

            if not _is_scraping_result_valid(query, snippet):
                msg = "네이버 스크래핑: '{}' 쿼리에서 질문에 맞는 실제 데이터를 찾지 못했습니다."
                last_error = msg.format(naver_query)
                continue

            # 예보 질의인데도 본문 스니펫이 '현재' 중심이면 오답이 나기 쉬우므로 반환하지 않습니다.
            if is_weather_query and is_forecast_weather:
                if location_tokens and not any(token in snippet for token in location_tokens):
                    last_error = "네이버 스크래핑: 예보 스니펫에서 요청 지역을 확인하지 못했습니다."
                    continue
                if not any(m in snippet for m in forecast_markers):
                    last_error = "네이버 스크래핑: 예보 스니펫에서 '내일/예보' 단서를 확인하지 못했습니다."
                    continue

            return f"[NAVER_SNIPPET]\nurl={url}\ncontent={snippet}", None

        default_msg = "네이버 스크래핑: 질문에 맞는 실제 데이터를 찾지 못했습니다."
        return None, last_error or default_msg
    except Exception as error:
        prefix = "네이버 스크래핑 오류"
        return None, f"{prefix}: {error}"


def web_search_with_status(query, max_results=3):
    """검색 소스를 순차적으로 시도하여 유효한 결과를 반환합니다."""
    collected_errors = []
    is_weather_query = _is_weather_query_text(query)
    is_forecast_weather = _is_forecast_weather_query(query) if is_weather_query else False

    # 예보(내일/주간 등)는 네이버가 JS 렌더링이라 스크래핑이 자주 실패합니다.
    # 키 없이 안정적으로 가져올 수 있는 Open-Meteo 예보를 우선 시도합니다.
    if is_weather_query and is_forecast_weather:
        try:
            fc = get_tomorrow_forecast_from_open_meteo(query)
            if fc:
                lines = [
                    "[OPEN_METEO_FORECAST]",
                    f"url={fc.source_url}",
                    f"location={fc.location_name}",
                    f"date={fc.date}",
                ]
                if fc.weather_summary:
                    lines.append(f"summary={fc.weather_summary}")
                if fc.tmin_c is not None:
                    lines.append(f"tmin_c={fc.tmin_c}")
                if fc.tmax_c is not None:
                    lines.append(f"tmax_c={fc.tmax_c}")
                if fc.precip_prob_max is not None:
                    lines.append(f"precip_prob_max={fc.precip_prob_max}")
                return {"content": "\n".join(lines), "provider": "open_meteo", "errors": []}
        except Exception as error:
            collected_errors.append(f"[예보 Open-Meteo] {error}")

    naver_result, naver_error = search_naver_direct(query)
    if naver_result:
        return {"content": naver_result, "provider": "naver_scraping", "errors": []}

    collected_errors.append(f"[0단계 네이버 스크래핑] {naver_error}")

    # '현재 날씨' 질문은 네이버 카드에서 현재값을 못 건지면 다른 검색 소스로 새지 않게 막습니다.
    # 그렇지 않으면 과거 날짜나 일반 설명을 끌고 와서 '지금 날씨' 질문에 틀린 답을 만들 수 있습니다.
    # 단, 예보(내일/주간 등) 질문은 네이버 카드 파싱 실패 시 다른 소스를 허용합니다.
    if is_weather_query and not is_forecast_weather:
        return {"content": None, "provider": None, "errors": collected_errors}

    fresh_keywords = ["주가", "주식", "환율", "현재", "오늘", "내일", "지금", "시세", "뉴스", "최신", "날짜"]
    enriched_query = query
    if any(k in query for k in fresh_keywords):
        now_str = datetime.datetime.now().strftime("%Y년 %m월 %d일")
        clean_query = re.sub(r"지금|현재|오늘", "", query).strip()
        enriched_query = f"{clean_query} {now_str}".strip()

    kr_domains = ["naver.com", "weather.go.kr", "kma.go.kr", "daum.net", "chosun.com", "mk.co.kr", "hankyung.com", "yna.co.kr"]
    tavily_result_kr, error_kr = search_tavily(enriched_query, max_results, kr_domains)
    if tavily_result_kr:
        return {"content": tavily_result_kr, "provider": "tavily (Korean Domains)", "errors": collected_errors}
    collected_errors.append(f"[1단계 Tavily KR] {error_kr}")

    tavily_result_gl, error_gl = search_tavily(enriched_query, max_results)
    if tavily_result_gl:
        return {"content": tavily_result_gl, "provider": "tavily (Global)", "errors": collected_errors}
    collected_errors.append(f"[2단계 Tavily Global] {error_gl}")

    duckduckgo_result, duckduckgo_error = search_duckduckgo(enriched_query, max_results)
    if duckduckgo_result:
        return {"content": duckduckgo_result, "provider": "duckduckgo (kr-kr)", "errors": collected_errors}
    collected_errors.append(f"[3단계 DuckDuckGo] {duckduckgo_error}")

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
