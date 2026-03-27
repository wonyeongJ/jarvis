"""RAG 기반 내부 문서 검색을 담당하는 서비스 모듈입니다."""

from __future__ import annotations

import atexit
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from core.paths import bundled_data_path, writable_path
from core.rag_runtime import build_document_context, configure_cache_environment, ensure_rag_backend


VECTOR_DB_PATH = bundled_data_path("vectordb")
HF_CACHE_DIR = writable_path("hf_cache")
MODEL_CACHE_DIR = bundled_data_path("model_cache")
configure_cache_environment(HF_CACHE_DIR, offline=getattr(sys, "frozen", False))
PROJECT_ROOT = Path(__file__).resolve().parents[2]
VENV_PYTHON = PROJECT_ROOT / "venv" / "Scripts" / "python.exe"
RAG_QUERY_WORKER_PATH = PROJECT_ROOT / "src" / "rag" / "rag_query_worker.py"

_rag_worker_process = None
_rag_worker_lock = threading.Lock()


def _should_prefer_rag_subprocess():
    """개발 실행에서는 RAG 전용 프로세스를 우선 사용합니다."""
    if getattr(sys, "frozen", False):
        return False
    return VENV_PYTHON.exists() and RAG_QUERY_WORKER_PATH.exists()


def _stop_rag_worker_process():
    """상주 RAG 워커 프로세스를 종료합니다."""
    global _rag_worker_process
    process = _rag_worker_process
    _rag_worker_process = None
    if not process:
        return

    try:
        if process.stdin:
            process.stdin.close()
    except Exception:
        pass

    try:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=3)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


atexit.register(_stop_rag_worker_process)


def _build_worker_env():
    env = os.environ.copy()
    existing_python_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(PROJECT_ROOT)
        if not existing_python_path
        else os.pathsep.join([str(PROJECT_ROOT), existing_python_path])
    )
    return env


def _start_rag_worker_process():
    """RAG 질의를 처리할 상주 워커를 시작합니다."""
    global _rag_worker_process

    if not _should_prefer_rag_subprocess():
        return None

    process = _rag_worker_process
    if process and process.poll() is None:
        return process

    try:
        process = subprocess.Popen(
            [str(VENV_PYTHON), str(RAG_QUERY_WORKER_PATH), "--server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=_build_worker_env(),
        )
    except Exception:
        _rag_worker_process = None
        return None

    try:
        ready_line = process.stdout.readline() if process.stdout else ""
        ready_payload = json.loads(ready_line.strip()) if ready_line else {}
    except Exception:
        ready_payload = {}

    if not ready_payload.get("ready"):
        _stop_rag_worker_process()
        return None

    _rag_worker_process = process
    return process


def warm_up_rag_backend():
    """앱 시작 시 RAG 백엔드를 백그라운드에서 미리 준비합니다."""
    if _should_prefer_rag_subprocess():
        _start_rag_worker_process()
        return
    ensure_rag_backend(VECTOR_DB_PATH, MODEL_CACHE_DIR, local_files_only=getattr(sys, "frozen", False))


def _search_documents_with_persistent_worker(query, top_k=5):
    """상주 RAG 워커에 질의를 보내 문맥을 받아옵니다."""
    with _rag_worker_lock:
        process = _start_rag_worker_process()
        if not process or not process.stdin or not process.stdout:
            return False, None

        payload = json.dumps({"query": query, "top_k": top_k}, ensure_ascii=False)
        try:
            process.stdin.write(payload + "\n")
            process.stdin.flush()
            response_line = process.stdout.readline()
        except Exception:
            _stop_rag_worker_process()
            return False, None

        if not response_line:
            _stop_rag_worker_process()
            return False, None

        try:
            response = json.loads(response_line.strip())
        except json.JSONDecodeError:
            return False, None

        if not response.get("ok"):
            return False, None
        return True, response.get("context")


def _search_documents_via_subprocess(query, top_k=5):
    """일회성 venv 서브프로세스로 RAG 검색을 수행합니다."""
    if not VENV_PYTHON.exists() or not RAG_QUERY_WORKER_PATH.exists():
        return False, None

    try:
        result = subprocess.run(
            [str(VENV_PYTHON), str(RAG_QUERY_WORKER_PATH), query, str(top_k)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            env=_build_worker_env(),
        )
    except Exception:
        return False, None

    stdout = (result.stdout or "").strip()
    if not stdout:
        return False, None

    last_line = stdout.splitlines()[-1]
    try:
        payload = json.loads(last_line)
    except json.JSONDecodeError:
        return False, None

    if not payload.get("ok"):
        return False, None

    return True, payload.get("context")


def search_documents(query, top_k=5):
    """주어진 질의에 대한 RAG 문맥 조각을 반환합니다."""
    if _should_prefer_rag_subprocess():
        executed, context = _search_documents_with_persistent_worker(query, top_k=top_k)
        if executed:
            return context
        executed, context = _search_documents_via_subprocess(query, top_k=top_k)
        if executed:
            return context

    embedding_model, rag_collection = ensure_rag_backend(VECTOR_DB_PATH, MODEL_CACHE_DIR, local_files_only=getattr(sys, "frozen", False))
    if not embedding_model or not rag_collection:
        executed, context = _search_documents_via_subprocess(query, top_k=top_k)
        if executed:
            return context
        return None

    try:
        return build_document_context(query, embedding_model, rag_collection, top_k=top_k)
    except Exception:
        executed, context = _search_documents_via_subprocess(query, top_k=top_k)
        if executed:
            return context
        return None
