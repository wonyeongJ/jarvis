"""Everything 기반 로컬 파일 검색을 담당하는 서비스 모듈입니다."""

from __future__ import annotations

import os
import re
import subprocess
import time

import requests

from core.paths import resource_path, writable_path
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


def _kill_all_everything_processes():
    """실행 중인 모든 Everything.exe 프로세스를 강제 종료합니다."""
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", "Everything.exe"],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        time.sleep(1.5)
    except Exception:
        pass


def _is_jarvis_everything_running():
    """현재 실행 중인 Everything.exe가 Jarvis assets 버전인지 확인합니다."""
    try:
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "Get-WmiObject Win32_Process -Filter \"Name='everything.exe'\" | Select-Object -ExpandProperty ExecutablePath",
            ],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=5,
        )
        running_paths = [p.strip().lower() for p in result.stdout.strip().splitlines() if p.strip()]
        jarvis_exe = os.path.join(EVERYTHING_BASE_DIR, "Everything.exe").lower()
        return any(p == jarvis_exe for p in running_paths)
    except Exception:
        return False


def _is_everything_service_installed():
    """Windows 서비스 목록에 Everything 이 등록되어 있는지 확인합니다."""
    try:
        result = subprocess.run(
            ["sc", "query", "Everything"],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=3,
        )
        return "Everything" in result.stdout
    except Exception:
        return False


def _install_everything_service(executable_path):
    """Everything 서비스를 관리자 권한으로 설치합니다 (최초 1회 UAC 팝업 발생)."""
    try:
        # PowerShell의 Start-Process -Verb RunAs 를 사용하여 
        # UAC 팝업을 띄우고 Everything.exe -install-service 를 실행합니다.
        cmd = f"Start-Process -FilePath '{executable_path}' -ArgumentList '-install-service' -Verb RunAs -WindowStyle Hidden"
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=10,
        )
        time.sleep(2.0)
    except Exception as e:
        print("Everything 서비스 설치 실패:", e)


def _update_appdata_everything_ini(port):
    """APPDATA 경로의 Everything.ini 파일을 완전히 깨끗하고 안전한 기본 설정으로 덮어씁니다."""
    appdata_dir = os.path.join(os.environ["APPDATA"], "Everything")
    os.makedirs(appdata_dir, exist_ok=True)
    ini_path = os.path.join(appdata_dir, "Everything.ini")

    # UAC 방지, 서비스 사용, HTTP 서버 활성화 및 고정 볼륨 자동 인덱싱 설정 강제화
    ini_content = f"""[Everything]
run_as_admin=0
everything_service=1
http_server_enabled=1
http_server_port={port}
allow_http_server=1
run_in_background=1
show_tray_icon=1
minimize_to_tray=1
close_on_execute=0
auto_include_fixed_volumes=1
"""
    try:
        with open(ini_path, "w", encoding="utf-8") as f:
            f.write(ini_content)
    except Exception as e:
        print("Everything.ini 파일 쓰기 실패:", e)


def start_everything():
    """Everything 이 설치되어 있고 실행 중이 아니면 실행합니다.

    시스템에 설치된 다른 Everything(HTTP 서버 비활성) 이 실행 중인 경우에도
    Jarvis assets 버전(HTTP 서버 활성)으로 교체합니다.
    """
    executable_path = os.path.join(EVERYTHING_BASE_DIR, "Everything.exe")
    if not os.path.exists(executable_path):
        return

    # Windows 서비스 등록 확인 및 자동 설치 (최초 1회 UAC 권한 요구)
    if not _is_everything_service_installed():
        _install_everything_service(executable_path)

    # APPDATA의 Everything.ini 파일을 업데이트하여 서비스 사용 및 포트를 바인딩시킵니다.
    _update_appdata_everything_ini(EVERYTHING_PORT)

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
            # 프로세스가 있지만 HTTP 서버 응답 없음 →
            # Jarvis assets 버전이 아닌 다른 인스턴스가 포트를 차지하고 있을 수 있으므로
            # 모두 종료하고 assets 버전으로 교체한다.
            _kill_all_everything_processes()
    except Exception:
        pass

    # -startup 플래그로 윈도우 창이 팝업되지 않고 백그라운드 트레이로 조용히 실행합니다.
    # 커스텀 config/db 지정을 없애 윈도우 백그라운드 서비스와 정상적으로 데이터베이스를 연동합니다.
    cmd_args = [
        executable_path,
        "-startup"
    ]

    subprocess.Popen(
        cmd_args,
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
