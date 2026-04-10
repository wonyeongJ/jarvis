from __future__ import annotations

import datetime
import re
from dataclasses import dataclass

import requests


@dataclass(frozen=True)
class ForecastResult:
    location_name: str
    date: str  # YYYY-MM-DD
    tmin_c: float | None
    tmax_c: float | None
    precip_prob_max: int | None  # 0-100
    weather_summary: str | None
    source_url: str


def _extract_location_hint(text: str) -> str | None:
    if not text:
        return None
    lowered = text.strip()
    # "… <지역> … 날씨/forecast/기온" 형태에서 <지역> 근처를 최대한 넓게 잡습니다.
    kw_match = re.search(r"(날씨|weather|forecast|기온|온도)", lowered, re.IGNORECASE)
    if not kw_match:
        return None
    before = lowered[: kw_match.start()]
    before = re.sub(r"[?!.]+$", "", before).strip()
    before = re.sub(r"\s+", " ", before)
    # 시간/요청 키워드 제거
    before = re.sub(r"\b(내일|모레|오늘|지금|현재|주간|이번주|다음주|주말|예보|시간별|알려줘|알려\s*줘|어때|어떠|좀)\b", " ", before, flags=re.IGNORECASE)
    before = re.sub(r"\s+", " ", before).strip()
    if not before:
        return None
    # 마지막 1~3 토큰을 지역 후보로 사용 (예: "세종 고운동" / "세종특별자치시 고운동")
    tokens = [t for t in before.split(" ") if t]
    hint_tokens = tokens[-3:] if len(tokens) >= 3 else tokens
    hint = " ".join(hint_tokens).strip()
    return hint or None


def _wmo_code_to_ko_summary(code: int | None) -> str | None:
    if code is None:
        return None
    # Open-Meteo uses WMO weather interpretation codes.
    if code == 0:
        return "맑음"
    if code in (1, 2, 3):
        return "구름"
    if code in (45, 48):
        return "안개"
    if code in (51, 53, 55, 56, 57):
        return "이슬비"
    if code in (61, 63, 65, 66, 67):
        return "비"
    if code in (71, 73, 75, 77):
        return "눈"
    if code in (80, 81, 82):
        return "소나기"
    if code in (85, 86):
        return "눈 소나기"
    if code in (95, 96, 99):
        return "뇌우"
    return None


def get_tomorrow_forecast_from_open_meteo(user_text: str, tz: str = "Asia/Seoul", timeout_s: int = 8) -> ForecastResult | None:
    """키 없이 사용 가능한 Open-Meteo로 '내일' 일간 예보를 가져옵니다.

    - Geocoding API로 위치를 찾고
    - Forecast API의 daily(tmin/tmax/precip_prob/weather_code)로 내일 값을 반환합니다.
    """
    location_hint = _extract_location_hint(user_text) or user_text.strip()
    if not location_hint:
        return None

    # Open-Meteo geocoding can be spotty for some Korean place names in Hangul,
    # especially 읍/면/동 단위. Provide a few high-signal fallback candidates.
    kr_fallback_names = {
        "서울": "Seoul",
        "부산": "Busan",
        "대구": "Daegu",
        "인천": "Incheon",
        "광주": "Gwangju",
        "대전": "Daejeon",
        "울산": "Ulsan",
        "세종": "Sejong",
        "제주": "Jeju",
    }
    geo_name_candidates = [location_hint]
    normalized_hint = re.sub(r"\s+", " ", location_hint).strip()
    tokens = normalized_hint.split(" ")
    if normalized_hint in kr_fallback_names:
        geo_name_candidates.append(kr_fallback_names[normalized_hint])
    # If query includes sublocality like "세종 고운동", also try the broader parent token(s).
    if len(tokens) >= 2:
        geo_name_candidates.append(tokens[0])
        geo_name_candidates.append(" ".join(tokens[:2]))
    # 읍/면/동/구 등 말단 행정단위는 제거한 후보도 시도
    if tokens:
        last = tokens[-1]
        if re.search(r"(동|읍|면|구)$", last):
            geo_name_candidates.append(" ".join(tokens[:-1]).strip())
    # Try English mapping for first token (e.g., "세종 고운동" -> "Sejong")
    if tokens and tokens[0] in kr_fallback_names:
        geo_name_candidates.append(kr_fallback_names[tokens[0]])
    # Also try adding country qualifier
    geo_name_candidates.append(f"{location_hint} South Korea")
    if len(tokens) >= 1:
        geo_name_candidates.append(f"{tokens[0]} South Korea")

    geo_url = "https://geocoding-api.open-meteo.com/v1/search"
    results = []
    seen_candidates = set()
    for candidate in geo_name_candidates:
        candidate = re.sub(r"\s+", " ", (candidate or "").strip())
        if not candidate or candidate in seen_candidates:
            continue
        seen_candidates.add(candidate)
        geo_params = {"name": candidate, "count": 5, "language": "ko", "format": "json"}
        geo = requests.get(geo_url, params=geo_params, timeout=timeout_s)
        geo.raise_for_status()
        geo_json = geo.json() or {}
        results = geo_json.get("results") or []
        if results:
            break
    if not results:
        return None

    # Pick first; optionally could prefer KR results
    pick = None
    for r in results:
        if (r.get("country_code") or "").upper() == "KR":
            pick = r
            break
    pick = pick or results[0]

    lat = pick.get("latitude")
    lon = pick.get("longitude")
    if lat is None or lon is None:
        return None

    location_name = pick.get("name") or location_hint
    admin1 = pick.get("admin1")
    country = pick.get("country")
    if admin1 and admin1 not in location_name:
        location_name = f"{admin1} {location_name}"
    if country and country != "South Korea":
        location_name = f"{location_name} ({country})"

    forecast_url = "https://api.open-meteo.com/v1/forecast"
    forecast_params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": tz,
        "daily": "temperature_2m_min,temperature_2m_max,precipitation_probability_max,weathercode",
    }
    fc = requests.get(forecast_url, params=forecast_params, timeout=timeout_s)
    fc.raise_for_status()
    fc_json = fc.json() or {}
    daily = fc_json.get("daily") or {}

    times = daily.get("time") or []
    tmin = daily.get("temperature_2m_min") or []
    tmax = daily.get("temperature_2m_max") or []
    pmax = daily.get("precipitation_probability_max") or []
    wcode = daily.get("weathercode") or []

    # Tomorrow by local date
    today = datetime.datetime.now(datetime.timezone.utc).astimezone().date()
    tomorrow = today + datetime.timedelta(days=1)
    tomorrow_str = tomorrow.isoformat()

    try:
        idx = times.index(tomorrow_str)
    except ValueError:
        # fallback: if API returns only today..n but not tomorrow, use index 1 if exists
        idx = 1 if len(times) > 1 else 0
        if idx >= len(times):
            return None
        tomorrow_str = times[idx]

    def _safe_get(arr, i):
        try:
            return arr[i]
        except Exception:
            return None

    tmin_v = _safe_get(tmin, idx)
    tmax_v = _safe_get(tmax, idx)
    pmax_v = _safe_get(pmax, idx)
    wcode_v = _safe_get(wcode, idx)

    summary = _wmo_code_to_ko_summary(wcode_v if isinstance(wcode_v, int) else None)

    source_url = f"{forecast_url}?latitude={lat}&longitude={lon}"
    return ForecastResult(
        location_name=location_name,
        date=tomorrow_str,
        tmin_c=float(tmin_v) if tmin_v is not None else None,
        tmax_c=float(tmax_v) if tmax_v is not None else None,
        precip_prob_max=int(pmax_v) if pmax_v is not None else None,
        weather_summary=summary,
        source_url=source_url,
    )

