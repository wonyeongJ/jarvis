"""RAG 문서 검색 결과를 안정적으로 후처리하는 유틸리티입니다.

문서명 직접 매칭, 핵심 키워드 중복도, 거리값을 함께 사용해
관련 문서만 문맥으로 넘기고 애매한 검색은 걸러냅니다.
"""

from __future__ import annotations

import re
from pathlib import Path


OVERVIEW_KEYWORDS = ["알려줘", "알려", "설명", "정리", "요약", "내용", "뭐야", "무슨", "소개"]
SPECIFIC_KEYWORDS = ["며칠", "몇일", "어떻게", "조건", "대상", "절차", "신청", "가능", "언제", "얼마", "제", "조"]
GENERIC_QUERY_TOKENS = {
    "우리",
    "회사",
    "사내",
    "규정",
    "제도",
    "내용",
    "알려",
    "알려줘",
    "뭐야",
    "무엇",
    "뭔가",
    "관련",
}


def normalize_match_text(text: str) -> str:
    """문서명과 질의를 비교하기 쉬운 형태로 정규화합니다."""
    normalized = Path(text).stem.lower()
    normalized = re.sub(r"[^0-9a-z가-힣\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def extract_query_keywords(query: str):
    """질의에서 일반 표현을 제외한 핵심 키워드를 추출합니다."""
    normalized = normalize_match_text(query)
    return {
        token
        for token in normalized.split()
        if len(token) >= 2 and token not in GENERIC_QUERY_TOKENS
    }


def list_indexed_filenames(collection):
    """벡터 컬렉션에 적재된 파일명 목록을 반환합니다."""
    results = collection.get(include=["metadatas"])
    return sorted({metadata.get("filename", "") for metadata in results.get("metadatas", []) if metadata.get("filename")})


def infer_candidate_filenames(query: str, filenames):
    """질의와 직접적으로 맞는 후보 파일명을 점수 순으로 반환합니다."""
    normalized_query = normalize_match_text(query)
    query_tokens = extract_query_keywords(query)
    candidates = []

    for filename in filenames:
        normalized_filename = normalize_match_text(filename)
        filename_tokens = {
            token for token in normalized_filename.split() if len(token) >= 2 and token not in GENERIC_QUERY_TOKENS
        }
        exact_match = normalized_filename and normalized_filename in normalized_query
        token_overlap = len(query_tokens & filename_tokens)
        if not exact_match and token_overlap == 0:
            continue
        score = 100 + len(normalized_filename) if exact_match else token_overlap * 10
        candidates.append((score, filename, exact_match))

    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates


def is_overview_query(query: str) -> bool:
    """질의가 문서 전체 개요를 묻는 형태인지 판단합니다."""
    normalized = normalize_match_text(query)
    has_overview_keyword = any(keyword in normalized for keyword in OVERVIEW_KEYWORDS)
    has_specific_keyword = any(keyword in normalized for keyword in SPECIFIC_KEYWORDS)
    return has_overview_keyword and not has_specific_keyword


def _chunk_index_from_id(chunk_id: str) -> int:
    """청크 ID 뒤의 숫자를 기준으로 정렬용 인덱스를 추출합니다."""
    match = re.search(r"_(\d+)$", chunk_id or "")
    return int(match.group(1)) if match else 10**9


def build_overview_context(collection, filename: str, max_chunks: int = 4):
    """문서 개요 질문일 때 문서 앞부분 청크를 순서대로 반환합니다."""
    results = collection.get(where={"filename": filename}, include=["documents", "metadatas"])
    ids = results.get("ids", [])
    documents = results.get("documents", [])
    metadata_items = results.get("metadatas", [])

    ordered_items = sorted(
        zip(ids, documents, metadata_items),
        key=lambda item: _chunk_index_from_id(item[0]),
    )
    context_chunks = []
    for _chunk_id, document, metadata in ordered_items[:max_chunks]:
        if not document:
            continue
        context_chunks.append(f"[문서: {metadata.get('filename', filename)}]\n{document}")
    return "\n\n---\n\n".join(context_chunks) if context_chunks else None


def _row_keyword_overlap(query_keywords, document: str, metadata) -> int:
    """질의 핵심 키워드가 청크 본문과 섹션명에 얼마나 겹치는지 계산합니다."""
    haystack = normalize_match_text(
        f"{metadata.get('filename', '')} {metadata.get('section_title', '')} {document[:500]}"
    )
    haystack_tokens = {token for token in haystack.split() if len(token) >= 2}
    return len(query_keywords & haystack_tokens)


def query_collection_chunks(collection, query: str, query_embedding, top_k: int = 5, filenames=None):
    """후보 파일 범위를 반영해 컬렉션 청크를 조회합니다."""
    filenames = filenames or []
    merged_rows = []
    query_keywords = extract_query_keywords(query)

    if filenames:
        for filename in filenames[:3]:
            result = collection.query(
                query_embeddings=[query_embedding],
                n_results=max(top_k, 4),
                where={"filename": filename},
                include=["documents", "metadatas", "distances"],
            )
            documents = result.get("documents", [[]])[0]
            metadata_items = result.get("metadatas", [[]])[0]
            distances = result.get("distances", [[]])[0]
            merged_rows.extend(zip(documents, metadata_items, distances))
    else:
        result = collection.query(
            query_embeddings=[query_embedding],
            n_results=max(top_k, 8),
            include=["documents", "metadatas", "distances"],
        )
        documents = result.get("documents", [[]])[0]
        metadata_items = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        merged_rows.extend(zip(documents, metadata_items, distances))

    unique_rows = []
    seen = set()
    for document, metadata, distance in merged_rows:
        key = (metadata.get("filename", ""), document[:120])
        if key in seen:
            continue
        seen.add(key)
        overlap = _row_keyword_overlap(query_keywords, document, metadata)
        unique_rows.append((document, metadata, distance, overlap))

    unique_rows.sort(key=lambda item: (-item[3], item[2], item[1].get("chunk_index", 10**9)))
    return unique_rows[:max(top_k, 5)]


def has_meaningful_match(query: str, rows, preferred_filename: str | None = None) -> bool:
    """검색 결과가 실제 질문과 의미 있게 맞는지 판정합니다."""
    if not rows:
        return False

    query_keywords = extract_query_keywords(query)
    top_row = rows[0]
    top_distance = top_row[2]
    top_overlap = top_row[3]

    if preferred_filename:
        return top_overlap >= 1 or top_distance <= 0.72

    if not query_keywords:
        return top_distance <= 0.45

    return top_overlap >= 1 and top_distance <= 0.78


def format_context_rows(rows, preferred_filename: str | None = None):
    """조회된 청크 목록을 LLM 입력용 문맥 문자열로 변환합니다."""
    if not rows:
        return None

    max_distance = 0.78 if preferred_filename else 0.76
    filtered_rows = [row for row in rows if row[2] <= max_distance and (preferred_filename or row[3] >= 1)]
    if not filtered_rows:
        filtered_rows = rows[:1] if preferred_filename else []

    context_chunks = []
    for document, metadata, _distance, _overlap in filtered_rows[:4]:
        filename = metadata.get("filename", "")
        context_chunks.append(f"[문서: {filename}]\n{document}")
    return "\n\n---\n\n".join(context_chunks) if context_chunks else None