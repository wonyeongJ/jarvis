"""RAG 질의를 별도 프로세스에서 처리하기 위한 워커 스크립트입니다.

개발 실행 환경에서는 Torch 초기화 비용과 예외 전파를 분리하기 위해
이 워커를 독립 프로세스로 실행할 수 있습니다.
또한 표준입력 기반 서버 모드와 단발성 질의 모드를 모두 지원합니다.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core.paths import writable_path
from core.rag_runtime import build_document_context, configure_cache_environment, ensure_rag_backend


VECTOR_DB_PATH = writable_path("vectordb")
HF_CACHE_DIR = writable_path("hf_cache")
MODEL_CACHE_DIR = writable_path("model_cache")
configure_cache_environment(HF_CACHE_DIR)


def _handle_request(query: str, top_k: int):
    """질의 하나를 처리해 JSON 응답 형태로 반환합니다."""
    embedding_model, rag_collection = ensure_rag_backend(VECTOR_DB_PATH, MODEL_CACHE_DIR)
    context = build_document_context(query, embedding_model, rag_collection, top_k=top_k)
    return {"ok": True, "context": context}


def run_server():
    """표준입력을 통해 여러 질의를 연속 처리하는 서버 모드입니다."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")

    try:
        ensure_rag_backend(VECTOR_DB_PATH, MODEL_CACHE_DIR)
        print(json.dumps({"ok": True, "ready": True}, ensure_ascii=False), flush=True)
    except Exception as error:
        print(
            json.dumps(
                {"ok": False, "error": str(error), "traceback": traceback.format_exc()},
                ensure_ascii=False,
            ),
            flush=True,
        )
        return 1

    for line in sys.stdin:
        message = line.strip()
        if not message:
            continue
        try:
            payload = json.loads(message)
            query = payload.get("query", "")
            top_k = int(payload.get("top_k", 5))
            response = _handle_request(query, top_k)
        except Exception as error:
            response = {"ok": False, "error": str(error), "traceback": traceback.format_exc()}
        print(json.dumps(response, ensure_ascii=False), flush=True)

    return 0


def main():
    """명령행 인자를 읽어 서버 또는 단발성 질의 모드를 실행합니다."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) >= 2 and sys.argv[1] == "--server":
        return run_server()

    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "질의를 입력해 주세요."}, ensure_ascii=False))
        return 1

    query = sys.argv[1]
    try:
        top_k = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    except ValueError:
        top_k = 5

    try:
        response = _handle_request(query, top_k)
        print(json.dumps(response, ensure_ascii=False))
        return 0
    except Exception as error:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(error),
                    "traceback": traceback.format_exc(),
                },
                ensure_ascii=False,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
