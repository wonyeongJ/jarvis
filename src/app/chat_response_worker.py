"""요청 라우팅과 응답 생성 흐름을 담당하는 백그라운드 워커입니다.

사용자 요청 유형을 분류하고 필요한 검색 단계를 거친 뒤,
Ollama 응답을 스트리밍 형태로 UI 에 전달합니다.
"""

import datetime
import json
import re

import requests
from PyQt5.QtCore import QThread, pyqtSignal

from core.request_routing import classify_user_request, summarize_project_folder
from services.search_facade import (
    is_everything_available,
    resolve_file_selection_command,
    search_documents,
    search_local_files,
    should_use_web_search,
    web_search_with_status,
)
from services.stock_analysis_service import (
    is_stock_analysis_query,
    is_stock_price_query,
    run_stock_quote,
    run_technical_analysis,
)


MAX_HISTORY_MESSAGES = 6
MAX_RAG_CONTEXT_CHARS = 1800
MAX_SEARCH_RESULT_CHARS = 2200
OLLAMA_MEMORY_SAVER_OPTIONS = {
    "num_ctx": 1024,
    "num_predict": 256,
}


class ChatResponseWorker(QThread):
    """현재 사용자 메시지에 대한 응답을 워커 스레드에서 생성합니다."""

    finished = pyqtSignal(str)
    search_status = pyqtSignal(str)
    streaming = pyqtSignal(str)
    pc_result = pyqtSignal(list)
    pc_failed = pyqtSignal(str)
    file_action = pyqtSignal(str, str)

    def __init__(self, history, model_name, system_prompt):
        """대화 이력과 모델 설정을 보관합니다."""
        super().__init__()
        self.history = history
        self.model_name = model_name
        self.system_prompt = system_prompt
        self.regex_mode = False

    def run(self):
        """최근 사용자 요청을 분류하고 필요한 문맥을 붙여 응답을 생성합니다."""
        last_user_message = next(
            (message["text"] for message in reversed(self.history) if message["role"] == "user"),
            "",
        )
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        request_type = classify_user_request(last_user_message)

        # 검색 대상이면 검색어를 정제하여 문맥을 반영합니다. (날씨 등 후속 질문 처리용)
        refined_query = self._refine_search_query(last_user_message)

        file_command_result = resolve_file_selection_command(last_user_message)
        if file_command_result:
            if file_command_result.startswith("__DELETE_CONFIRM__"):
                self.file_action.emit("delete", file_command_result[len("__DELETE_CONFIRM__"):])
            elif file_command_result.startswith("__COPY_TO_DESKTOP__"):
                self.file_action.emit("copy", file_command_result[len("__COPY_TO_DESKTOP__"):])
            else:
                self.finished.emit(file_command_result)
            return

        document_context = None
        search_result = None

        # 주가 조회 요청은 yfinance 값으로 직접 응답 (LLM 재해석 방지)
        if is_stock_price_query(refined_query) and not is_stock_analysis_query(refined_query):
            self.search_status.emit("📈 주가 데이터를 조회하는 중입니다...")
            quote_text, quote_error = run_stock_quote(refined_query)
            if quote_text:
                self.finished.emit(quote_text)
                return
            if quote_error:
                self.finished.emit(quote_error)
                return

        # ★ 기술적 분석 요청은 request_type에 무관하게 최우선으로 처리
        if is_stock_analysis_query(refined_query):
            self.search_status.emit("📈 주식 기술적 분석 데이터를 수집하는 중입니다...")
            analysis_text, analysis_error = run_technical_analysis(refined_query)
            if analysis_text:
                search_result = analysis_text
                request_type = "stock_analysis"
            elif analysis_error:
                if self._is_stock_dependency_error(analysis_error):
                    self.finished.emit(analysis_error)
                    return
                # 종목 미인식 등 → 웹 검색으로 fallback
                search_result = self._run_web_search(refined_query)
                if search_result is None:
                    return
                direct_weather_answer = self._build_direct_weather_answer(refined_query, search_result)
                if direct_weather_answer:
                    self.finished.emit(direct_weather_answer)
                    return

        if request_type == "pc":
            self.search_status.emit("🔎 PC 파일을 검색하는 중입니다...")
            noise_pattern = r"(\s*내\s*pc에서|\s*제\s*pc에서|\s*내\s*컴퓨터에서|\s*제\s*컴퓨터에서|\s*내\s*pc|\s*제\s*pc|\s*내\s*컴퓨터|\s*제\s*컴퓨터|찾아줘|검색해줘|어디\s*있어|있나|있어|파일|문서)"
            keyword = re.sub(noise_pattern, "", last_user_message, flags=re.IGNORECASE).strip()
            keyword = re.sub(r"\s+", " ", keyword).strip()
            if not keyword:
                self.pc_failed.emit("검색어를 인식하지 못했습니다.")
                return
            if not is_everything_available():
                self.pc_failed.emit("아직 Everything 인덱싱 중입니다. 잠시 후 다시 시도해 주세요.")
                return
            items = search_local_files(keyword)
            if items == "__TIMEOUT__":
                self.pc_failed.emit("Everything 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.")
                return
            if items is None:
                self.pc_failed.emit("로컬 파일 검색 서비스에 연결하지 못했습니다.")
                return
            if not items:
                self.pc_failed.emit(f"'{keyword}' 검색 결과가 없습니다.")
                return
            self.pc_result.emit(items)
            return

        if request_type == "rag":
            self.search_status.emit("📚 내부 문서를 검색하는 중입니다...")
            document_context = search_documents(last_user_message, top_k=3)
            if not document_context:
                self.finished.emit(
                    "현재 내부 문서 기준으로는 질문과 정확히 맞는 내용을 찾지 못했습니다. "
                    "관련 규정이 있다면 documents 폴더에 문서가 들어 있는지 확인해 주세요."
                )
                return
        elif request_type == "web":
            # ★ 기술적 분석 요청이면 yfinance 분석을 먼저 시도
            if is_stock_analysis_query(refined_query):
                self.search_status.emit("📈 주식 기술적 분석 데이터를 수집하는 중입니다...")
                analysis_text, analysis_error = run_technical_analysis(refined_query)
                if analysis_text:
                    search_result = analysis_text
                    request_type = "stock_analysis"
                elif analysis_error:
                    if self._is_stock_dependency_error(analysis_error):
                        self.finished.emit(analysis_error)
                        return
                    # 종목 미인식 또는 데이터 오류 → 일반 웹 검색으로 fallback
                    self.search_status.emit(f"⚠️ 기술적 분석 실패 ({analysis_error}) — 웹 검색으로 전환합니다...")
                    search_result = self._run_web_search(refined_query)
                    if search_result is None:
                        return
                    direct_weather_answer = self._build_direct_weather_answer(refined_query, search_result)
                    if direct_weather_answer:
                        self.finished.emit(direct_weather_answer)
                        return
            else:
                self.search_status.emit("🌐 웹 검색을 진행하는 중입니다...")
                search_result = self._run_web_search(refined_query)
                if search_result is None:
                    return
                direct_weather_answer = self._build_direct_weather_answer(refined_query, search_result)
                if direct_weather_answer:
                    self.finished.emit(direct_weather_answer)
                    return
        elif request_type == "error":
            self.search_status.emit("🧯 오류 내용을 분석하는 중입니다...")
        elif request_type == "sql":
            self.search_status.emit("🗄 SQL 답변을 준비하는 중입니다...")
        elif request_type == "regex":
            self.search_status.emit("🧩 정규식을 생성하는 중입니다...")
            self.regex_mode = True
        elif request_type == "dev":
            self.search_status.emit("💻 코드 답변을 준비하는 중입니다...")
        elif request_type == "folder":
            path_match = re.search(r"[A-Za-z]:\\[^\s]+|/[^\s]+", last_user_message)
            self.search_status.emit("🗂 프로젝트 폴더를 분석하는 중입니다...")
            if path_match:
                search_result = summarize_project_folder(path_match.group(0))
        elif should_use_web_search(refined_query):
            # ★ 기술적 분석 요청이면 yfinance 분석을 먼저 시도
            if is_stock_analysis_query(refined_query):
                self.search_status.emit("📈 주식 기술적 분석 데이터를 수집하는 중입니다...")
                analysis_text, analysis_error = run_technical_analysis(refined_query)
                if analysis_text:
                    search_result = analysis_text
                    request_type = "stock_analysis"
                elif analysis_error:
                    if self._is_stock_dependency_error(analysis_error):
                        self.finished.emit(analysis_error)
                        return
                    self.search_status.emit(f"⚠️ 기술적 분석 실패 ({analysis_error}) — 웹 검색으로 전환합니다...")
                    search_result = self._run_web_search(refined_query)
                    if search_result is None:
                        return
                    direct_weather_answer = self._build_direct_weather_answer(refined_query, search_result)
                    if direct_weather_answer:
                        self.finished.emit(direct_weather_answer)
                        return
            else:
                self.search_status.emit("🌐 웹 검색을 진행하는 중입니다...")
                search_result = self._run_web_search(refined_query)
                if search_result is None:
                    return
                direct_weather_answer = self._build_direct_weather_answer(refined_query, search_result)
                if direct_weather_answer:
                    self.finished.emit(direct_weather_answer)
                    return

        messages = self._build_messages(last_user_message, now_str, request_type, document_context, search_result)
        payload = {"model": self.model_name, "messages": messages, "stream": True, "options": OLLAMA_MEMORY_SAVER_OPTIONS}

        try:
            response = requests.post("http://localhost:11434/api/chat", json=payload, timeout=120, stream=True)
            response.raise_for_status()
            full_response = ""
            for line in response.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                token = chunk.get("message", {}).get("content", "")
                full_response += token
                self.streaming.emit(token)
                if chunk.get("done"):
                    break

            if full_response.strip():
                self.finished.emit(full_response)
            else:
                self.finished.emit("응답을 생성하지 못했습니다. 다시 한 번 요청해 주세요.")
        except Exception as error:
            self.finished.emit(f"Jarvis 오류: Ollama 연결에 실패했습니다.\n\n{error}")

    def _is_stock_dependency_error(self, error_message: str) -> bool:
        """yfinance 의존성 관련 오류 여부를 판단합니다."""
        lowered = (error_message or "").lower()
        return "yfinance" in lowered

    def _is_weather_query(self, query):
        """날씨 질문 여부를 간단히 판단합니다."""
        return any(keyword in query for keyword in ["날씨", "기온", "온도"])

    def _build_direct_weather_answer(self, query, search_result):
        """네이버 현재 날씨 결과는 LLM을 거치지 않고 바로 답변합니다."""
        if not self._is_weather_query(query):
            return None
        if not search_result or not search_result.startswith("[NAVER_WEATHER]"):
            return None

        data = {}
        for line in search_result.splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key == "url":
                continue
            data[key.strip()] = value.strip()

        current_temp = data.get("temp")
        weather = data.get("weather")
        feels_like = data.get("feels_like")
        humidity = data.get("humidity")
        summary = data.get("summary")
        location = data.get("basis") or data.get("location") or "해당 지역"
        wind = data.get("wind")

        if not current_temp:
            return None

        parts = []
        headline = f"현재 {location} 날씨는"
        if weather:
            headline += f" {weather}, {current_temp}입니다."
        else:
            headline += f" {current_temp}입니다."
        parts.append(headline)

        details = []
        if feels_like:
            details.append(f"체감 {feels_like}")
        if humidity:
            details.append(f"습도 {humidity}")
        if wind:
            details.append(f"바람 {wind}")
        if details:
            parts.append(", ".join(details) + "입니다.")

        extras = []
        if data.get("dust"):
            extras.append(f"미세먼지 {data['dust']}")
        if data.get("ultrafine_dust"):
            extras.append(f"초미세먼지 {data['ultrafine_dust']}")
        if data.get("uv"):
            extras.append(f"자외선 {data['uv']}")
        if extras:
            parts.append(", ".join(extras) + "입니다.")
        elif summary:
            parts.append(summary + ".")

        return " ".join(parts)

    def _run_web_search(self, query):
        """웹 검색을 수행하고 실패 시 사용자에게 원인을 안내합니다."""
        search_status = web_search_with_status(query)
        if search_status.get("content"):
            return search_status["content"]

        errors = search_status.get("errors", [])
        details = "\n".join(f"- {error}" for error in errors) if errors else "- 원인을 확인하지 못했습니다."
        self.finished.emit(
            "웹 검색 결과를 가져오지 못했습니다.\n\n"
            "확인된 원인:\n"
            f"{details}"
        )
        return None

    def _truncate_text(self, text, limit):
        """너무 긴 문맥은 앞부분만 남기고 잘라냅니다."""
        normalized = text.strip()
        if len(normalized) <= limit:
            return normalized
        return normalized[:limit].rstrip() + "\n...(중략)"

    def _build_messages(self, last_user_message, now_str, request_type, document_context, search_result):
        """현재 요청 유형에 맞는 Ollama 메시지 payload 를 구성합니다."""
        messages = [{"role": "system", "content": self.system_prompt}]

        if document_context:
            compact_document_context = self._truncate_text(document_context, MAX_RAG_CONTEXT_CHARS)
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"[현재 시각: {now_str}]\n\n"
                        f"사용자 질문: {last_user_message}\n\n"
                        f"[내부 문서 검색 결과]\n"
                        "아래 내용만 근거로 답변해 주세요. 없는 내용은 추측해서 추가하지 말아 주세요. "
                        "사용자가 요청하지 않으면 파일명은 굳이 언급하지 말아 주세요.\n"
                        "문서 원본에 불특정 다수(예: '여러분')를 향한 인삿말이 있어도 그대로 복사하지 말고, 반드시 '마스터'라는 호칭만을 사용하여 충성스럽게 대답하세요.\n\n"
                        f"{compact_document_context}"
                    ),
                }
            )
            return messages

        if request_type == "error":
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "다음 오류 또는 예외를 분석해 주세요.\n\n"
                        f"[오류]\n{last_user_message}\n\n"
                        "아래 형식을 그대로 지켜 답변해 주세요.\n"
                        "## 원인\n(설명)\n\n"
                        "## 해결 방법\n(구체적인 조치)\n\n"
                        "## 수정 코드\n```java 또는 sql\n(수정 코드)\n```"
                    ),
                }
            )
            return messages

        if request_type == "sql":
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Oracle SQL 전문가처럼 답변하고 Oracle 전용 문법을 우선 사용해 주세요.\n\n"
                        f"요청: {last_user_message}\n\n"
                        "- NVL, DECODE, TO_DATE, ROWNUM, CONNECT BY 같은 Oracle 함수를 우선 사용\n"
                        "- 코드는 ```sql 블록으로 작성\n"
                        "- 쿼리 아래에 핵심 설명 추가"
                    ),
                }
            )
            return messages

        if request_type == "regex":
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Java 정규식 전문가처럼 답변해 주세요.\n\n"
                        f"요청: {last_user_message}\n\n"
                        "아래 형식을 그대로 지켜 답변해 주세요.\n"
                        "## 정규식 패턴\n```java\nPattern.compile(\"pattern\");\n```\n\n"
                        "## 패턴 설명\n(각 부분 설명)\n\n"
                        "## 사용 예시\n```java\n(예시 코드)\n```\n\n"
                        "## 테스트 케이스\n(매칭되는 값 / 매칭되지 않는 값)"
                    ),
                }
            )
            return messages

        if request_type == "dev":
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Java, Spring Legacy, 전자정부 프레임워크 전문가처럼 답변해 주세요.\n\n"
                        f"요청: {last_user_message}\n\n"
                        "- 엔터프라이즈 Java 와 Spring Legacy 관점 우선\n"
                        "- 필요하면 MyBatis mapper 스타일 반영\n"
                        "- 코드는 fenced code block 으로 작성\n"
                        "- 코드 주석은 한국어로 작성"
                    ),
                }
            )
            return messages

        if request_type == "stock_analysis" and search_result:
            compact_search_result = self._truncate_text(search_result, MAX_SEARCH_RESULT_CHARS)
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"[현재 시각: {now_str}]\n\n"
                        f"마스터의 질문: {last_user_message}\n\n"
                        "[실시간 기술적 분석 데이터]\n"
                        f"{compact_search_result}\n\n"
                        "---\n"
                        "위 기술적 분석 데이터를 바탕으로 아래 형식에 맞춰 답변해 주세요.\n\n"
                        "⚠️ 필수 준수 사항 (어기면 틀린 답변입니다):\n"
                        "1. 답변 전체를 반드시 순수한 한국어로만 작성하세요. 한자·중국어·일본어 등 어떤 외국 문자도 절대 포함하지 마세요.\n"
                        "2. 출처(URL, 링크, '※ 출처:' 등)는 절대 작성하지 마세요. 데이터는 이미 신뢰할 수 있는 실시간 소스에서 직접 수집되었습니다.\n"
                        "3. 위 데이터에 없는 내용은 상상하거나 지어내지 마세요.\n\n"
                        "## 종합 현황\n"
                        "(현재가, 등락 방향 한 줄 요약)\n\n"
                        "## 지표별 해석\n"
                        "- RSI: (과매수/과매도/중립 여부와 의미)\n"
                        "- MACD: (골든크로스/데드크로스 여부와 모멘텀 방향)\n"
                        "- 볼린저밴드: (밴드 내 위치와 의미)\n"
                        "- 이동평균: (정배열/역배열 여부와 추세 방향)\n"
                        "- 거래량: (평균 대비 거래량 활성도)\n\n"
                        "## 종합 의견\n"
                        "(위 지표들을 종합한 단기 기술적 현황 해석. 투자 조언은 하지 마세요.)"
                    ),
                }
            )
            return messages


        if request_type == "folder" and search_result:
            compact_search_result = self._truncate_text(search_result, MAX_SEARCH_RESULT_CHARS)
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "다음 프로젝트 구조와 파일 조각을 분석해 주세요.\n\n"
                        f"{compact_search_result}\n\n"
                        f"분석 요청: {last_user_message}\n\n"
                        "아래 항목으로 정리해 주세요.\n"
                        "1. 프로젝트 개요\n"
                        "2. 기술 스택\n"
                        "3. 구조 요약\n"
                        "4. 위험 요소 또는 개선점"
                    ),
                }
            )
            return messages

        if search_result:
            compact_search_result = self._truncate_text(search_result, MAX_SEARCH_RESULT_CHARS)
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"[현재 시각: {now_str}]\n\n"
                        f"사용자 질문: {last_user_message}\n\n"
                        "[검색 결과]\n"
                        f"{compact_search_result}\n\n"
                        "---\n"
                        "위 검색 결과만 근거로 답변하세요. 검색 결과에 없는 내용은 추측해서 추가하지 마세요.\n\n"
                        "규칙 1. 사용자가 특정 지역을 말했으면 그 지역 정보만 답변하세요. 다른 지역 이야기는 섞지 마세요.\n"
                        "규칙 2. 사용자가 '지금', '현재', '오늘'을 물었으면 현재 시점 정보만 답변하세요. 내일, 모레, 주간 예보, 과거 날짜는 사용자가 직접 묻지 않은 한 절대 꺼내지 마세요.\n"
                        "규칙 3. 날씨 질문이면 검색 결과 안의 현재 날씨 카드 정보만 짧고 분명하게 전달하세요. 현재 기온, 체감, 날씨 상태처럼 지금 시점 정보가 있으면 그것만 우선 답하세요.\n"
                        "규칙 4. 검색 결과에 현재 정보가 없으면 지어내지 말고 '검색 결과에서 현재 정보를 확인하지 못했습니다.'라고만 답하세요. 7~10일 예보 같은 일반론은 말하지 마세요.\n"
                        "규칙 5. 출처 URL, 링크, '검색 결과를 반영했습니다' 같은 안내 문구는 절대 쓰지 마세요. 인사말도 빼고 바로 핵심만 답하세요.\n"
                    ),
                }
            )
            return messages

        is_simple_message = len(last_user_message.strip()) < 10
        history_to_send = [] if is_simple_message else self.history[-MAX_HISTORY_MESSAGES:]
        for index, message in enumerate(history_to_send):
            role = "user" if message["role"] == "user" else "assistant"
            content = message["text"]
            if role == "user" and index == len(history_to_send) - 1:
                content = f"[현재 시각: {now_str}]\n{content}\n\n(반드시 한국어로만 답변해 주세요)"
            messages.append({"role": role, "content": content})

        if is_simple_message:
            messages.append(
                {
                    "role": "user",
                    "content": f"[현재 시각: {now_str}]\n{last_user_message}\n\n(반드시 한국어로만 답변해 주세요)",
                }
            )

        return messages

    def _refine_search_query(self, query):
        """LLM을 사용하여 사용자 질문을 웹 검색(네이버)에 최적화된 키워드로 변환합니다."""
        # 최근 대화 문맥 추출 (최근 3개 메시지 정도)
        history_context = []
        # 현재 history 에 마지막 사용자 메시지가 이미 포함되어 있을 수 있으므로 슬라이싱에 주의
        # 보통 self.history 에는 현재 요청을 포함한 전체 이력이 들어있음
        recent_history = self.history[-4:-1] if len(self.history) > 1 else []
        for msg in recent_history:
            role_map = {"user": "사용자", "assistant": "어시스턴트", "system": "시스템"}
            role = role_map.get(msg["role"], msg["role"])
            history_context.append(f"{role}: {msg['text']}")
        
        context_str = "\n".join(history_context) if history_context else "이전 대화 없음"
        
        prompt = (
            "당신은 검색어 최적화 전문가입니다. 사용자의 질문과 대화 문맥을 분석하여 실시간 정보를 찾기 위한 '네이버 검색 키워드' 딱 하나만 출력하세요.\n\n"
            "[이전 대화 문맥]\n"
            f"{context_str}\n\n"
            "[검색어 생성 규칙]\n"
            "1. 특히 날씨나 미세먼지 질문의 경우, 네이버 날씨 카드가 반드시 나타날 수 있도록 지역명과 '날씨' 키워드를 포함하세요.\n"
            "2. 동네 이름(동/읍/면)만 있으면 상위 지자체(시/군)를 포함하여 검색어를 만드세요. (예: '고운동 날씨' -> '세종 고운동 날씨')\n"
            "3. '조치원 말고 고운동' 처럼 비교나 정정 표현이 있으면 최종 목적지인 지역만 남기세요.\n"
            "4. 이전 대화에서 날씨를 묻고 있었다면, 이번 질문에 '날씨' 단어가 없어도 자동으로 '날씨' 키워드를 붙이세요.\n"
            "5. 불필요한 수식어나 '알려줘', '어때?' 같은 문장은 모두 제외하고 검색어만 단답형으로 응답하세요.\n\n"
            f"사용자 질문: {query}\n"
            "검색어:"
        )
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": OLLAMA_MEMORY_SAVER_OPTIONS
        }
        try:
            response = requests.post("http://localhost:11434/api/chat", json=payload, timeout=10)
            if response.status_code == 200:
                refined = response.json().get("message", {}).get("content", "").strip()
                # 따옴표나 불필요한 공백 제거
                refined = re.sub(r'["\']', '', refined).strip()
                # 간혹 '검색어: 키워드' 형태로 나오는 경우 처리
                if ":" in refined and len(refined.split(":")[0]) < 10:
                    refined = refined.split(":", 1)[1].strip()
                return refined if refined else query
        except Exception:
            pass
        return query


