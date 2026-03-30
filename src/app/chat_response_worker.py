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
                self.pc_failed.emit("Everything ?? ??? ???? ????. ?? ? ?? ??? ???.")
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
            document_context = search_documents(last_user_message)
            if not document_context:
                self.finished.emit(
                    "현재 내부 문서 기준으로는 질문과 정확히 맞는 내용을 찾지 못했습니다. "
                    "관련 규정이 있다면 documents 폴더에 문서가 들어 있는지 확인해 주세요."
                )
                return
        elif request_type == "web":
            self.search_status.emit("🌐 웹 검색을 진행하는 중입니다...")
            search_result = self._run_web_search(last_user_message)
            if search_result is None:
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
        elif should_use_web_search(last_user_message):
            self.search_status.emit("🌐 웹 검색을 진행하는 중입니다...")
            search_result = self._run_web_search(last_user_message)
            if search_result is None:
                return

        messages = self._build_messages(last_user_message, now_str, request_type, document_context, search_result)
        payload = {"model": self.model_name, "messages": messages, "stream": True}

        try:
            response = requests.post("http://localhost:11434/api/chat", json=payload, timeout=120, stream=True)
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

            if document_context:
                full_response = "[📚 내부 문서 문맥을 반영했습니다]\n\n" + full_response
            elif search_result:
                full_response = "[🔍 검색 결과를 반영했습니다]\n\n" + full_response
            self.finished.emit(full_response)
        except Exception as error:
            self.finished.emit(f"Jarvis 오류: Ollama 연결에 실패했습니다.\n\n{error}")

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

    def _build_messages(self, last_user_message, now_str, request_type, document_context, search_result):
        """현재 요청 유형에 맞는 Ollama 메시지 payload 를 구성합니다."""
        messages = [{"role": "system", "content": self.system_prompt}]

        if document_context:
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
                        f"{document_context}"
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

        if request_type == "folder" and search_result:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "다음 프로젝트 구조와 파일 조각을 분석해 주세요.\n\n"
                        f"{search_result}\n\n"
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
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"[현재 시각: {now_str}]\n\n"
                        f"사용자 질문: {last_user_message}\n\n"
                        "[검색 결과]\n"
                        f"{search_result}\n\n"
                        "---\n"
                        "위 [검색 결과]를 보고 아래 규칙을 반드시 지켜서 답변하세요.\n\n"
                        "※ 모든 규칙은 예외 없이 적용됩니다. 규칙을 어기는 답변은 틀린 답변입니다.\n\n"
                        "규칙 0. [범위 제한] 사용자가 특정 지역·종목을 지정했으면 그 지역·종목 정보만 답변하세요.\n"
                        "        예) '세종 날씨'를 물으면 세종 정보만. 경기·충북·전남 등 다른 지역은 한 글자도 포함 금지.\n"
                        "규칙 1. [수치 전달] 검색 결과에 정확한 수치(기온, 주가 등)가 있으면 그 수치를 그대로 전달하세요.\n"
                        "규칙 2. [정보 없음] 검색 결과에 원하는 정보가 없으면 절대 지어내거나 예상하지 마세요.\n"
                        "        아래 두 문장만 그대로 출력하세요:\n"
                        "        '검색 결과에서 해당 정보를 찾지 못했습니다.\n"
                        "         일반적으로 날씨 예보는 7~10일 전부터 확인 가능합니다. 죄송합니다.'\n"
                        "규칙 3. [출처] 정확한 정보를 찾았을 때만 '[웹사이트명](URL)' 형식으로 답변 끝에 출처를 표시하세요.\n"
                        "        정보를 찾지 못했을 때는 출처를 절대 표시하지 마세요.\n"
                        "규칙 4. [단위] 화씨(°F) 등 미국식 단위는 한국 기준(°C, km 등)으로 변환해 자연스럽게 녹여내세요.\n"
                        "규칙 5. [문체] 직역투나 중복 표현을 피해 자연스러운 한국어로 작성하세요.\n"
                    ),
                }
            )
            return messages

        is_simple_message = len(last_user_message.strip()) < 10
        history_to_send = [] if is_simple_message else self.history
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