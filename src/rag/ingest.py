"""documents 폴더의 문서를 읽어 벡터 DB 를 재생성하는 실행 스크립트입니다.

새 문서를 추가하거나 기존 문서를 수정한 뒤 이 스크립트를 실행하면,
현재 문서 집합 기준으로 검색 가능한 벡터 데이터를 갱신합니다.
"""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core.paths import writable_path
from core.rag_ingestion import (
    create_collection,
    create_embedding_model,
    iter_document_paths,
    read_document_text,
    upsert_document,
)


DOCUMENTS_DIR = Path(writable_path("documents"))
VECTOR_DB_DIR = writable_path("vectordb")
MODEL_CACHE_DIR = writable_path("model_cache")


def rebuild_vector_db():
    """documents 폴더 기준으로 벡터 DB 를 다시 생성합니다."""
    collection = create_collection(VECTOR_DB_DIR)
    embedding_model = create_embedding_model(MODEL_CACHE_DIR)

    total_chunks = 0
    processed_files = 0
    for document_path in iter_document_paths(DOCUMENTS_DIR):
        try:
            text = read_document_text(document_path)
            chunk_count = upsert_document(collection, embedding_model, document_path.name, text)
            processed_files += 1
            total_chunks += chunk_count
            print(f"적재 완료: {document_path.name} ({chunk_count}개 청크)")
        except Exception as error:
            print(f"적재 실패: {document_path.name} - {error}")

    print(f"완료: {processed_files}개 파일, 총 {total_chunks}개 청크")


if __name__ == "__main__":
    rebuild_vector_db()
