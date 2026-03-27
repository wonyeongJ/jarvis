"""애플리케이션 환경설정을 읽는 공용 모듈입니다.

민감정보나 환경별 설정값을 소스코드에 직접 넣지 않고
프로젝트 루트의 .env 파일에서 읽어오도록 합니다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ENV_LOADED = False


DEFAULT_OLLAMA_MODEL_NAME = "llama3.1:8b"
DEFAULT_EVERYTHING_PORT = 8888
DEFAULT_RAG_COLLECTION_NAME = "jarvis_docs"
DEFAULT_RAG_EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"


def _iter_env_paths():
    """실행 환경에 따라 우선순위가 있는 .env 후보 경로를 반환합니다."""
    candidates = []

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / ".env")
        if hasattr(sys, "_MEIPASS"):
            candidates.append(Path(sys._MEIPASS) / ".env")

    candidates.append(PROJECT_ROOT / ".env")

    seen = set()
    for candidate in candidates:
        normalized = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        yield candidate


def load_app_env():
    """앱 전체에서 .env 를 한 번만 읽도록 보장합니다."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return

    if load_dotenv is not None:
        for env_path in _iter_env_paths():
            if env_path.exists():
                load_dotenv(env_path)
                break

    _ENV_LOADED = True


def get_env(name: str, default: str | None = None):
    """문자열 형태의 환경변수 값을 반환합니다."""
    load_app_env()
    return os.getenv(name, default)


def get_int_env(name: str, default: int) -> int:
    """정수형 환경변수를 읽고 실패하면 기본값을 반환합니다."""
    value = get_env(name)
    if value in (None, ""):
        return default
    try:
        return int(value)
    except ValueError:
        return default


def get_ollama_model_name() -> str:
    """Ollama 모델명을 반환합니다."""
    return get_env("OLLAMA_MODEL_NAME", DEFAULT_OLLAMA_MODEL_NAME)


def get_everything_port() -> int:
    """Everything HTTP 포트를 반환합니다."""
    return get_int_env("EVERYTHING_PORT", DEFAULT_EVERYTHING_PORT)


def get_rag_collection_name() -> str:
    """Chroma 컬렉션 이름을 반환합니다."""
    return get_env("RAG_COLLECTION_NAME", DEFAULT_RAG_COLLECTION_NAME)


def get_rag_embedding_model() -> str:
    """RAG 임베딩 모델명을 반환합니다."""
    return get_env("RAG_EMBEDDING_MODEL", DEFAULT_RAG_EMBEDDING_MODEL)
