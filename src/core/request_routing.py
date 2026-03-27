"""사용자 요청의 성격을 분류하는 라우팅 유틸리티입니다.

이 모듈은 파일 검색, 사내 문서 검색, 웹 검색, 오류 분석,
정규식 생성, 일반 대화 같은 요청 유형을 판별합니다.

[라우팅 우선순위]
  1. pc      — "내 PC에서 ~" 같은 로컬 파일 검색 요청
  2. rag     — 사내 문서/규정 관련 질문 (웹 키워드보다 먼저 확인)
  3. normal  — 5글자 미만 짧은 입력
  4. web     — 실시간 정보가 필요한 질문 (명확한 키워드 또는 의도 기반)
  5. error   — 스택트레이스, ORA- 오류 등 오류 분석 요청
  6. sql     — SQL/Oracle 쿼리 작성 요청
  7. regex   — 정규식 패턴 생성 요청
  8. folder  — 프로젝트 폴더 구조 분석 요청
  9. dev     — Java/Spring 등 개발 코드 작성 요청
 10. normal  — 위 어디에도 해당하지 않는 일반 대화
"""

import os
import re


# ---------------------------------------------------------------------------
# 오류 감지 패턴
# Java 스택트레이스, Spring 예외, Oracle ORA- 오류 등을 인식합니다.
# ---------------------------------------------------------------------------
ERROR_PATTERNS = [
    r"at\s+[\w\.\$]+\([\w\.]+:\d+\)",   # Java 스택트레이스 한 줄
    r"Exception in thread",               # JVM 스레드 예외 헤더
    r"Caused by:",                        # 중첩 예외 원인
    r"ORA-\d{4,5}",                       # Oracle 오류 코드
    r"java\.lang\.\w+Exception",          # java.lang.* 예외 클래스
    r"org\.springframework\.",            # Spring 프레임워크 패키지
    r"NullPointerException",              # NPE (패키지 없이 단독 등장 시)
    r"ClassNotFoundException",            # 클래스 로딩 실패
    r"SQLException",                      # JDBC/SQL 예외
    r"Error\s*:\s*\d+",                   # 숫자 오류 코드 패턴
]

# ---------------------------------------------------------------------------
# RAG 키워드 — 사내 문서 벡터 검색을 트리거합니다.
# "오늘 연차" 처럼 WEB 키워드와 겹치는 경우가 있으므로
# WEB 키워드보다 반드시 먼저 확인합니다.
# ---------------------------------------------------------------------------
RAG_KEYWORDS = [
    "인사 규정",
    "사내",
    "회사 규정",
    "복지",
    "연차",
    "병가",
    "휴가",
    "법인카드",
    "자격증 수당",
    "근속",
    "경조사",
    "복리후생",
    "출산휴가",
    "경조금",
    "급여",
    "징계휴가",
]

# ---------------------------------------------------------------------------
# WEB 키워드 — 두 종류로 분리해 오분류를 줄입니다.
#
# WEB_KEYWORDS        : 단독으로도 웹 검색이 필요한 명확한 단어
# WEB_AMBIGUOUS_KEYWORDS : "오늘", "현재" 처럼 맥락에 따라 달라지는 단어.
#                         이 단어들은 SEARCH_INTENT_PATTERNS 과 함께 등장할
#                         때만 web 으로 분류합니다.
# ---------------------------------------------------------------------------
WEB_KEYWORDS = [
    # 시사·금융 정보
    "뉴스",
    "주식",
    "주가",
    "환율",
    # 날씨
    "날씨",
    "기온",
    "기상",
    "비 와",
    "눈 와",
    # 트렌드·동향 (복합 표현으로만 사용)
    "최신 트렌드",
    "최근 동향",
]

WEB_AMBIGUOUS_KEYWORDS = [
    # 단독으로는 일반 대화에도 자주 등장하는 단어
    "오늘",
    "지금",
    "현재",
    "최신",
    "최근",
    "요즘",
    "얼마",
]

# WEB_AMBIGUOUS_KEYWORDS 와 함께 등장하면 웹 검색 의도로 판단합니다.
SEARCH_INTENT_PATTERNS = [
    r"검색해\s*줘",
    r"찾아\s*줘",
    r"알려\s*줘",
    r"얼마야",
    r"얼마예요",
    r"얼마지",
]

# ---------------------------------------------------------------------------
# SQL 키워드 — Oracle SQL 및 일반 RDBMS 작업 요청을 인식합니다.
# ---------------------------------------------------------------------------
SQL_KEYWORDS = [
    "sql",
    "쿼리",
    "select",
    "insert",
    "update",
    "delete",
    "oracle",
    "테이블",
    "조인",
    "join",
    "where",
    "프로시저",
    "function",
    "트리거",
    "인덱스",
    "뷰 만들기",
    "view 만들기",
]

# ---------------------------------------------------------------------------
# 정규식 키워드
# ---------------------------------------------------------------------------
REGEX_KEYWORDS = [
    "정규식",
    "정규표현식",
    "regex",
    "regexp",
    "패턴 만들기",
    "패턴 짜줘",
]

# ---------------------------------------------------------------------------
# 폴더/프로젝트 분석 키워드
# FOLDER_ANALYSIS_KEYWORDS 와 FOLDER_TARGET_KEYWORDS 가 모두 있을 때만
# folder 로 분류합니다.
# ---------------------------------------------------------------------------
FOLDER_ANALYSIS_KEYWORDS = [
    "폴더 분석",
    "프로젝트 분석",
    "구조 분석",
    "분석해줘",
]
FOLDER_TARGET_KEYWORDS = [
    "폴더",
    "프로젝트",
    "경로",
]

# ---------------------------------------------------------------------------
# 개발 키워드 — Java/Spring/전자정부 등 코드 생성 요청을 인식합니다.
# ---------------------------------------------------------------------------
DEV_KEYWORDS = [
    "java",
    "spring",
    "jsp",
    "jquery",
    "javascript",
    "자바",
    "스프링",
    "만들어줘",
    "메서드 만들어줘",
    "함수 만들어줘",
    "코드 짜줘",
    "코드 작성",
    "구현해줘",
    "전자정부",
    "mybatis",
    "mapper",
    "service",
    "controller",
    "html 만들어줘",
    "css 만들어줘",
    "ajax",
]


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------

def _needs_web_search(text: str) -> bool:
    """웹 검색이 필요한지 키워드와 의도를 함께 판단합니다.

    명확한 WEB_KEYWORDS 가 있으면 즉시 True 를 반환하고,
    WEB_AMBIGUOUS_KEYWORDS 는 검색 의도 표현과 함께 등장할 때만 True 를 반환합니다.
    """
    # 명확한 웹 키워드 — 단독으로 충분
    if any(keyword in text for keyword in WEB_KEYWORDS):
        return True

    # 애매한 키워드는 검색 의도 표현이 동반될 때만 web 으로 분류
    has_ambiguous = any(keyword in text for keyword in WEB_AMBIGUOUS_KEYWORDS)
    has_intent = any(re.search(pattern, text) for pattern in SEARCH_INTENT_PATTERNS)
    return has_ambiguous and has_intent


# ---------------------------------------------------------------------------
# 공개 함수
# ---------------------------------------------------------------------------

def looks_like_error_report(text: str) -> bool:
    """입력이 스택트레이스나 SQL 오류처럼 보이는지 판별합니다."""
    return any(re.search(pattern, text) for pattern in ERROR_PATTERNS)


def summarize_project_folder(folder_path: str) -> str | None:
    """지정한 프로젝트 폴더의 구조와 샘플 파일 내용을 요약합니다.

    최대 깊이 3, 트리 라인 80줄, 샘플 파일 5개로 제한해
    LLM 컨텍스트가 너무 커지지 않도록 합니다.
    """
    if not os.path.isdir(folder_path):
        return None

    result = [f"[프로젝트 경로] {folder_path}\n"]

    # 폴더 트리 수집 (불필요한 빌드·캐시 폴더 제외)
    SKIP_DIRS = {".git", "node_modules", "target", "build", ".idea", "__pycache__", ".svn", "bin", "out"}
    tree_lines = []
    for root, dirs, files in os.walk(folder_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        depth = root.replace(folder_path, "").count(os.sep)
        if depth > 3:
            continue
        indent = "  " * depth
        tree_lines.append(f"{indent}- {os.path.basename(root)}/")
        sub_indent = "  " * (depth + 1)
        for file_name in files[:10]:
            tree_lines.append(f"{sub_indent}- {file_name}")

    result.append("[폴더 구조]")
    result.append("\n".join(tree_lines[:80]))

    # 주요 확장자 파일을 최대 5개까지 앞부분만 읽어 첨부
    SAMPLE_EXTENSIONS = {".java", ".jsp", ".xml", ".properties", ".yml", ".sql"}
    samples = []
    for root, dirs, files in os.walk(folder_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for file_name in files:
            if len(samples) >= 5:
                break
            if os.path.splitext(file_name)[1].lower() not in SAMPLE_EXTENSIONS:
                continue
            file_path = os.path.join(root, file_name)
            try:
                with open(file_path, encoding="utf-8", errors="ignore") as f:
                    content_sample = f.read(800)
                relative_path = os.path.relpath(file_path, folder_path)
                samples.append(f"\n[파일: {relative_path}]\n{content_sample}\n...")
            except Exception:
                continue

    if samples:
        result.append("\n[주요 파일 샘플]")
        result.extend(samples)

    return "\n".join(result)


def classify_user_request(question: str) -> str:
    """사용자 요청을 워커가 처리할 라우팅 유형으로 분류합니다.

    반환값 목록:
        "pc"     — Everything 로컬 파일 검색
        "rag"    — 사내 문서 벡터 검색
        "web"    — 웹 검색 (Tavily → DuckDuckGo 폴백)
        "error"  — 오류/예외 분석
        "sql"    — Oracle SQL 작성
        "regex"  — Java 정규식 생성
        "folder" — 프로젝트 폴더 구조 분석
        "dev"    — Java/Spring 코드 작성
        "normal" — 일반 대화
    """
    normalized = question.strip()
    normalized_lower = normalized.lower()

    # 1. PC 파일 검색 — "내 PC에서 ~", "컴퓨터에서 ~"
    if any(keyword in normalized_lower for keyword in ["pc", "컴퓨터", "pc에서", "컴퓨터에서"]):
        return "pc"

    # 2. 사내 문서(RAG) — WEB 키워드와 겹치는 단어("연차" 등)가 있어 먼저 확인
    if any(keyword in normalized for keyword in RAG_KEYWORDS):
        return "rag"

    # 3. 너무 짧은 입력은 일반 대화로 처리
    if len(normalized) < 5:
        return "normal"

    # 4. 웹 검색 — 명확한 키워드 또는 (애매한 키워드 + 검색 의도) 조합
    if _needs_web_search(normalized):
        return "web"

    # 5. 오류/예외 분석 — 스택트레이스, ORA- 코드 등
    if looks_like_error_report(normalized):
        return "error"

    # 6. SQL/Oracle 쿼리 작성
    if any(keyword in normalized_lower for keyword in SQL_KEYWORDS):
        return "sql"

    # 7. 정규식 패턴 생성
    if any(keyword in normalized_lower for keyword in REGEX_KEYWORDS):
        return "regex"

    # 8. 폴더/프로젝트 구조 분석 — 분석 키워드 + 대상 키워드 모두 필요
    if any(keyword in normalized_lower for keyword in FOLDER_ANALYSIS_KEYWORDS) and \
       any(keyword in normalized_lower for keyword in FOLDER_TARGET_KEYWORDS):
        return "folder"

    # 9. Java/Spring 개발 코드 작성
    if any(keyword in normalized_lower for keyword in DEV_KEYWORDS):
        return "dev"

    # 10. 위 어디에도 해당하지 않으면 일반 대화
    return "normal"


def should_use_web_search(text: str) -> bool:
    """웹 검색 필요 여부를 classify_user_request 와 동일한 기준으로 판단합니다.

    chat_response_worker 에서 request_type 이 "normal" 로 분류된 이후
    추가로 웹 검색 여부를 확인할 때 사용합니다.
    _needs_web_search() 를 공유하므로 두 함수의 판단 기준이 항상 일치합니다.
    """
    normalized = text.strip()
    if len(normalized) < 5:
        return False

    # 인사말·감탄사 등 명백한 비검색 입력 제외
    NO_SEARCH_EXACT = {"헤이", "hi", "hello", "안녕", "응", "그래", "네", "아니", "맞아", "고마워", "좋네"}
    NO_SEARCH_STARTS = ["안녕", "고마워", "감사", "수고", "좋아", "오케", "그리고", "대박", "응", "네"]
    if normalized.lower() in NO_SEARCH_EXACT:
        return False
    if any(normalized.startswith(prefix) for prefix in NO_SEARCH_STARTS):
        return False

    return _needs_web_search(normalized)