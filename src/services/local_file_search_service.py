"""Everything 기반 로컬 파일 검색을 담당하는 서비스 모듈입니다."""

from __future__ import annotations

import os
import re
import subprocess
import time

import requests

from core.paths import resource_path
from core.settings import get_everything_port
from services.file_action_service import open_parent_folder, open_path


EVERYTHING_PORT = get_everything_port()
EVERYTHING_BASE_DIR = resource_path("everything")
EVERYTHING_READY_MIN_TOTAL_RESULTS = 100
EVERYTHING_RESULT_LIMIT = 100
EVERYTHING_SEARCH_RETRY_STEPS = [
    {"count": 50, "timeout": (0.5, 6)},
    {"count": 100, "timeout": (1, 10)},
    {"count": 100, "timeout": (1, 15)},
]
RECENT_FILE_SEARCH_PATHS = []


def _request_everything_payload(query, count=EVERYTHING_RESULT_LIMIT, timeout=(0.5, 6)):
    """Everything HTTP 서버에 검색 요청을 보내고 원본 응답 payload 를 반환합니다."""
    response = requests.get(
        f"http://127.0.0.1:{EVERYTHING_PORT}",
        params={
            "search": query,
            "json": 1,
            "path_column": 1,
            "extension_column": 1,
            "type_column": 1,
            "count": count,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def _request_everything_results(query, count=EVERYTHING_RESULT_LIMIT, timeout=(0.5, 6)):
    """Everything HTTP 서버에 검색 요청을 보내고 결과 목록을 반환합니다."""
    data = _request_everything_payload(query, count=count, timeout=timeout)
    return data.get("results", [])


def is_everything_available():
    """Everything HTTP 서버가 실제 검색 가능한 상태인지 확인합니다."""
    try:
        data = _request_everything_payload("", count=5, timeout=(0.5, 1.5))
        total_results = int(data.get("totalResults", 0) or 0)
        return total_results >= EVERYTHING_READY_MIN_TOTAL_RESULTS
    except Exception:
        return False


def start_everything():
    """Everything 이 설치되어 있고 실행 중이 아니면 실행합니다."""
    executable_path = os.path.join(EVERYTHING_BASE_DIR, "Everything.exe")
    if not os.path.exists(executable_path):
        return

    if is_everything_available():
        return

    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Everything.exe", "/NH"],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if "Everything.exe" in result.stdout:
            # 프로세스는 있지만 응답이 없는 상태이므로 재시작 시도
            subprocess.run(
                ["taskkill", "/F", "/IM", "Everything.exe"],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            time.sleep(1)
    except Exception:
        pass

    # Everything.ini의 설정을 존중하여 백그라운드(-startup)로만 실행합니다.
    subprocess.Popen(
        [executable_path, "-startup"],
        cwd=EVERYTHING_BASE_DIR,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def wait_for_everything(attempts: int = 40, delay_seconds: float = 0.5):
    """Everything HTTP 서버가 실제 검색 가능한 상태가 될 때까지 잠시 대기합니다."""
    for _ in range(attempts):
        if is_everything_available():
            return True
        time.sleep(delay_seconds)
    return False


def launch_everything():
    """Everything 을 시작하고 검색 가능한 상태가 될 때까지 기다립니다."""
    start_everything()
    wait_for_everything()


def build_file_search_query(text):
    """자연어 요청을 Everything 검색 문자열로 변환합니다."""
    normalized = text.lower()
    extension_map = {
        "pdf": "ext:pdf",
        "엑셀": "ext:xlsx",
        "excel": "ext:xlsx",
        "워드": "ext:docx",
        "word": "ext:docx",
        "ppt": "ext:pptx",
        "파워포인트": "ext:pptx",
        "사진": "ext:jpg|ext:png",
        "이미지": "ext:jpg|ext:png",
    }

    extension_filter = ""
    for keyword, filter_value in extension_map.items():
        if keyword in normalized:
            extension_filter = filter_value
            break

    stopwords = [
        "내 pc에서",
        "내 컴퓨터에서",
        "제 pc에서",
        "제 컴퓨터에서",
        "내 pc",
        "내 컴퓨터",
        "제 pc",
        "제 컴퓨터",
        "좀",
        "pc",
        "컴퓨터",
        "에서",
        "찾아줘",
        "검색해줘",
        "검색",
        "관련",
        "파일",
        "문서",
        "있는",
        "있어",
        "있나",
        "어디",
        "내",
        "제",
    ]
    for stopword in stopwords:
        normalized = normalized.replace(stopword, "")

    normalized = normalized.strip()
    return f"{normalized} {extension_filter}".strip()


def score_file_result(name, keyword):
    """파일명이 검색어와 얼마나 잘 맞는지 간단히 점수화합니다."""
    return sum(10 for word in keyword.split() if word.lower() in name.lower())


def _search_with_retry_steps(query):
    last_error = None
    for step in EVERYTHING_SEARCH_RETRY_STEPS:
        try:
            return _request_everything_results(query, count=step["count"], timeout=step["timeout"])
        except requests.exceptions.RequestException as error:
            last_error = error
            print("Everything 재시도 오류:", error)
            time.sleep(1)
    raise last_error if last_error else RuntimeError("Everything 검색에 실패했습니다.")


def search_local_files(keyword):
    """Everything 으로 로컬 파일을 검색하고 화면용 결과 목록을 반환합니다."""
    query = build_file_search_query(keyword)

    try:
        results = _search_with_retry_steps(query)
    except requests.exceptions.RequestException as error:
        print("Everything 검색 오류:", error)
        launch_everything()
        try:
            results = _search_with_retry_steps(query)
        except requests.exceptions.ReadTimeout:
            return "__TIMEOUT__"
        except requests.exceptions.RequestException:
            return None
    except Exception as error:
        print("Everything 검색 오류:", error)
        return None

    if not results:
        return []

    results.sort(key=lambda item: score_file_result(item["name"], query), reverse=True)
    seen_paths = set()
    RECENT_FILE_SEARCH_PATHS.clear()
    display_items = []
    for item in results:
        name = item["name"]
        folder = item["path"]
        full_path = os.path.join(folder, name)
        if full_path in seen_paths:
            continue
        seen_paths.add(full_path)
        icon = "📁" if item.get("type") == "folder" else "📄"
        RECENT_FILE_SEARCH_PATHS.append(full_path)
        display_items.append((icon, name, folder, full_path))
        if len(display_items) >= EVERYTHING_RESULT_LIMIT:
            break
    return display_items


def resolve_file_selection_command(question):
    """최근 파일 검색 결과를 기준으로 번호 후속 명령을 해석합니다."""
    match = re.search(r"(\d+)번", question)
    if not match:
        return None

    index = int(match.group(1)) - 1
    if index < 0 or index >= len(RECENT_FILE_SEARCH_PATHS):
        return "해당 번호에 맞는 파일이 없습니다."

    path = RECENT_FILE_SEARCH_PATHS[index]

    if any(keyword in question for keyword in ["삭제", "지워", "지워줘", "없앨까"]):
        return f"__DELETE_CONFIRM__{path}"

    if any(keyword in question for keyword in ["복사", "복사해줘", "카피"]):
        return f"__COPY_TO_DESKTOP__{path}"

    if any(
        keyword in question
        for keyword in ["폴더 열어", "폴더열어", "폴더 오픈", "경로 열어", "경로열어", "위치 열어", "위치열어"]
    ):
        target = path if os.path.isdir(path) else os.path.dirname(path)
        try:
            open_parent_folder(path)
            return f"폴더를 열었습니다.\n{target}"
        except Exception as error:
            return f"실행에 실패했습니다.\n{error}"

    try:
        open_path(path)
        return f"파일을 열었습니다.\n{path}"
    except Exception as error:
        return f"실행에 실패했습니다.\n{error}"
