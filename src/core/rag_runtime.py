"""RAG 런타임 초기화와 문맥 생성을 공통으로 제공하는 모듈입니다.

검색 서비스와 별도 워커 프로세스가 같은 기준으로 벡터 DB 와 임베딩 모델을
초기화하고, 문서 문맥을 생성할 수 있도록 중복 로직을 한곳에 모읍니다.
"""

from __future__ import annotations

import os

from core.settings import get_rag_collection_name, get_rag_embedding_model

from core.rag_retrieval import (
    build_overview_context,
    format_context_rows,
    has_meaningful_match,
    infer_candidate_filenames,
    is_overview_query,
    list_indexed_filenames,
    query_collection_chunks,
)


_embedding_model = None
_rag_collection = None
_backend_checked = False


def configure_cache_environment(hf_cache_dir: str, offline: bool = False):
    """Hugging Face 계열 캐시 경로를 공통 규칙으로 설정합니다."""
    os.environ.setdefault("HF_HOME", hf_cache_dir)
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", os.path.join(hf_cache_dir, "hub"))
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", os.path.join(hf_cache_dir, "sentence_transformers"))
    os.environ.setdefault("TRANSFORMERS_CACHE", os.path.join(hf_cache_dir, "transformers"))
    if offline:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


def ensure_rag_backend(vector_db_path: str, model_cache_dir: str, local_files_only: bool = False):
    """RAG 백엔드를 실제로 필요할 때 한 번만 지연 로딩합니다."""
    global _embedding_model, _rag_collection, _backend_checked

    if _backend_checked:
        return _embedding_model, _rag_collection

    _backend_checked = True

    try:
        import chromadb
        from sentence_transformers import SentenceTransformer

        _embedding_model = SentenceTransformer(
            get_rag_embedding_model(),
            cache_folder=model_cache_dir,
            local_files_only=local_files_only,
        )
        chroma_client = chromadb.PersistentClient(path=vector_db_path)
        _rag_collection = chroma_client.get_or_create_collection(
            name=get_rag_collection_name(),
            metadata={"hnsw:space": "cosine"},
        )
    except Exception:
        _embedding_model = None
        _rag_collection = None

    return _embedding_model, _rag_collection


def build_document_context(query: str, embedding_model, rag_collection, top_k: int = 5):
    """질의에 맞는 사내 문서 문맥을 구성해 반환합니다."""
    indexed_filenames = list_indexed_filenames(rag_collection)
    candidates = infer_candidate_filenames(query, indexed_filenames)
    if candidates and candidates[0][2] and is_overview_query(query):
        context = build_overview_context(rag_collection, candidates[0][1], max_chunks=min(top_k, 4))
        if context:
            return context

    query_embedding = embedding_model.encode(query).tolist()
    candidate_filenames = [filename for _score, filename, _exact_match in candidates]
    rows = query_collection_chunks(rag_collection, query, query_embedding, top_k=top_k, filenames=candidate_filenames)
    preferred_filename = candidate_filenames[0] if candidate_filenames else None
    if not has_meaningful_match(query, rows, preferred_filename=preferred_filename):
        return None
    return format_context_rows(rows, preferred_filename=preferred_filename)
