"""호환용 루트 진입점입니다.

기존 실행 습관을 유지할 수 있도록 scripts/jarvis.py 로 위임합니다.
"""

from pathlib import Path
import runpy


SCRIPT_PATH = Path(__file__).resolve().parent / "scripts" / "jarvis.py"
runpy.run_path(str(SCRIPT_PATH), run_name="__main__")
