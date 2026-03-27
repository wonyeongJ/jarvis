"""리소스 경로와 쓰기 가능한 데이터 경로를 계산하는 유틸리티입니다.

개발 실행과 PyInstaller 빌드 실행이 서로 다른 디렉터리 구조를 쓰더라도
같은 코드에서 정적 리소스와 런타임 데이터를 안정적으로 찾을 수 있게 합니다.
"""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ASSETS_ROOT = PROJECT_ROOT / "assets"
DATA_ROOT = PROJECT_ROOT / "data"


def resource_path(relative_path):
    """정적 리소스의 실제 경로를 반환합니다."""
    if hasattr(sys, "_MEIPASS"):
        base_path = Path(sys._MEIPASS) / "assets"
    else:
        base_path = ASSETS_ROOT
    return str(base_path / relative_path)


def bundled_data_path(relative_path):
    """읽기 전용으로 번들된 데이터 경로를 반환합니다."""
    if hasattr(sys, "_MEIPASS"):
        internal_path = Path(sys._MEIPASS) / "data" / relative_path
        if internal_path.exists():
            return str(internal_path)
    return str(DATA_ROOT / relative_path)


def _has_any_contents(path: Path) -> bool:
    """디렉터리에 실제 내용물이 하나라도 있는지 확인합니다."""
    try:
        return any(path.iterdir())
    except OSError:
        return False


def writable_path(relative_path):
    """쓰기 가능한 런타임 데이터 경로를 반환합니다.

    빌드 실행에서는 아래 순서로 경로를 선택합니다.
    1. exe 옆 data 폴더에 실제 내용이 있으면 그 경로 사용
    2. 번들된 _internal/data 폴더에 내용이 있으면 그 경로 사용
    3. 둘 다 없으면 exe 옆 data 폴더를 생성해 사용

    이 규칙은 비어 있는 런타임 폴더가 번들 리소스를 가리는 문제를 막습니다.
    """
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidate = exe_dir / "data" / relative_path
        internal = Path(sys._MEIPASS) / "data" / relative_path

        if candidate.exists():
            if candidate.is_file() or _has_any_contents(candidate):
                return str(candidate)

        if internal.exists():
            return str(internal)

        if candidate.exists():
            return str(candidate)

        candidate.mkdir(parents=True, exist_ok=True)
        return str(candidate)

    full_path = DATA_ROOT / relative_path
    full_path.mkdir(parents=True, exist_ok=True)
    return str(full_path)
