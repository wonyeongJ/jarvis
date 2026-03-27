"""Jarvis ???? ?? ??????.

? ??? scripts ??? ???? ?? ??? PyInstaller ?? ???
?? ??? ??? ????? ???.
"""

import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
VENV_PYTHON = PROJECT_ROOT / "venv" / "Scripts" / "python.exe"
VENV_SITE_PACKAGES = PROJECT_ROOT / "venv" / "Lib" / "site-packages"
TORCH_LIB_DIR = VENV_SITE_PACKAGES / "torch" / "lib"
RELAUNCH_ENV_KEY = "JARVIS_RELAUNCHED_WITH_VENV"


if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core.settings import load_app_env
load_app_env()


def _is_running_in_venv_python():
    """?? ????? ???? venv ????? ?????."""
    return Path(sys.executable).resolve() == VENV_PYTHON.resolve() if VENV_PYTHON.exists() else False


def _relaunch_with_project_venv():
    """?? ????? ??? ?? ???? venv ? ?? ?????."""
    if getattr(sys, "frozen", False):
        return
    if not VENV_PYTHON.exists():
        return
    if _is_running_in_venv_python():
        return
    if os.environ.get(RELAUNCH_ENV_KEY) == "1":
        return

    env = os.environ.copy()
    env[RELAUNCH_ENV_KEY] = "1"
    result = subprocess.run([str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]], env=env)
    raise SystemExit(result.returncode)


def _bootstrap_local_venv():
    """?? ?? ?? ? venv ???? DLL ??? ?? ?????."""
    if getattr(sys, "frozen", False):
        return

    if VENV_SITE_PACKAGES.exists() and str(VENV_SITE_PACKAGES) not in sys.path:
        sys.path.insert(0, str(VENV_SITE_PACKAGES))

    if hasattr(os, "add_dll_directory") and TORCH_LIB_DIR.exists():
        try:
            os.add_dll_directory(str(TORCH_LIB_DIR))
        except OSError:
            pass


if __name__ == "__main__":
    _relaunch_with_project_venv()

_bootstrap_local_venv()

from app.main_window import main


if __name__ == "__main__":
    raise SystemExit(main())
