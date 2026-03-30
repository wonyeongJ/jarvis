# Jarvis: 비서

Jarvis는 Windows 환경에서 실행하는 데스크톱 전용 '비서' AI 도우미입니다.

## 📌 1. 프로젝트 개요 (Introduction)

**Jarvis**는 회사 내의 복잡한 문서(PDF) 규정부터 사용자의 로컬 컴퓨터 수백만 개의 파일, 그리고 외부 웹 실시간 정보까지 하나로 통합하여 대답해 주는 궁극의 AI 어시스턴트입니다.

### 주요 기능 요약
- 🤖 **Ollama 기반 로컬 LLM 채팅**
- 📚 **사내 PDF 문서 RAG 검색**
- 🔍 **Everything 기반 초고속 PC 파일 검색**
- ⚡ **네이버 실시간 다이렉트 스크래핑 (`bs4` 활용):** 날씨, 주식 등 파편화된 실시간 위젯 정보를 탁월하게 짚어내 환각 없이 정확히 보고
- 🛡️ **마스터 페르소나 & 환각 차단 시스템:** 프롬프트 튜닝을 통해 아는 척하지 않고 오직 신뢰도 높은 데이터만 제공
- 🔗 **스마트 URL 오픈 연동:** 대화 속 마크다운 출처 링크 클릭 시 사용자 기본 웹 브라우저 즉시 실행
- 🖥️ **와이드 채팅 UI & 현지화 최적화:** 가독성이 극대화된 넓은 말풍선 시야각 제공 및 해외 단위(°F)의 대한민국 표준 단위(°C) 자동 치환
- 💾 **채팅 이력 로컬 안전 저장 및 PyInstaller 1클릭 빌드**

### 🛠️ 핵심 기술 스택 (Tech Stack)
소스코드를 공부하거나 기능 확장을 기획 중인 개발자를 위한 기술 요약입니다.

**🟢 Core & GUI**
- **Python (v3.12.2) / PyQt5**: 마스터 컨트롤러 백엔드와 데스크톱 창(Window) 인터페이스 구축

**🔴 AI & NLP (로컬 LLM 및 RAG)**
- **Ollama (기본 모델: `llama3.1:8b`)**: 인터넷 연결 없이 완벽한 보안 환경에서 작동하는 로컬 언어 모델 코어
- **ChromaDB**: PDF 문서 기반 질문(RAG)을 처리하기 위한 로컬 벡터 데이터베이스 (Vector DB)
- **SentenceTransformers**: 로컬 텍스트의 문맥을 계산해서 벡터 값으로 변환해주는 경량화 AI

**🔵 Data & Search Pipeline (정보 탐색부)**
- **Everything (voidtools)**: 윈도우 OS의 레지스트리를 읽어 1초 만에 PC 파일과 폴더를 모조리 찾아내는 극한의 탐색 엔진
- **BeautifulSoup4 (bs4) & lxml**: 네이버 등 국내 검색 엔진 0순위 실시간 파싱(스크래핑) 모듈 (최신 파편화 위젯 데이터 즉시 수집)
- **Tavily Search API**: 정교한 기술 및 최신 웹 문맥을 수집하는 타겟팅 웹 검색 API 파이프라인
- **DuckDuckGo (DDG)**: 환율/단위 등 보조 검색을 커버하는 후순위 지역화 검색 모듈

**🟡 Deployment (배포)**
- **PyInstaller**: 앞선 모든 무거운 라이브러리와 런타임 모델 캐시를 하나의 단일 `.exe` 프로그램 덩어리로 압축 패키징

---

## 🚀 2. 빠른 시작 (Quick Start)

### 🥇 [일반 사용자용] 1분 만에 실행하기
개발 환경을 모르는 **일반 사용자**라면 빌드된 `.exe` 파일만 클릭하면 됩니다!

1. **Ollama 사전 설치**: LLM(인공지능) 뇌 역할을 하는 코어 엔진을 다운로드합니다.
   - 다운로드: `https://ollama.com/download`
   - 기본 모델 설치: 터미널에서 `ollama pull llama3.1:8b` 실행
2. **Jarvis 실행**: 배포받은 폴더 안에서 `dist\jarvis\jarvis.exe` 를 더블클릭합니다.

### 🥈 [개발자용] 소스 기반 실행하기
코드를 수정하거나 튜닝하려는 **개발자** 전용 명령어입니다.

```powershell
# 1. 가상환경 생성 및 필수 패키지 설치
python -m venv venv
venv\Scripts\pip install -r requirements.txt

# 2. (선택사항) 환경설정 파일 복제
copy .env.example .env

# 3. 개발용 런타임 바로 가동
venv\Scripts\python.exe jarvis.py
```

### 자주 쓰는 명령어 요약 

| 목적             | 명령어                                                                     |
| ---------------- | -------------------------------------------------------------------------- |
| **앱 실행**          | `venv\Scripts\python.exe jarvis.py`                                        |
| **벡터 DB 색인**   | `venv\Scripts\python.exe src\rag\ingest.py`                                |
| **워커 백엔드 테스트**  | `venv\Scripts\python.exe src\rag\rag_query_worker.py "휴가 규정 알려줘" 1` |
| **실행파일(exe) 빌드**        | `scripts\build_jarvis.bat`                                                 |

---

## 👤 3. 일반 사용자 가이드 (User Guide)

### Jarvis로 할 수 있는 주요 동작
- **웹 실시간 검색**: "세종 일기예보 어때", "카카오 주가 알려줘" 등 동적 위젯 데이터가 필요한 질문 시, 네이버를 다이렉트로 스크래핑하여 절대적으로 정확한 정보를 가져옵니다.
- **내부 문서 질문**: "회사 연차 규정 알려줘" 와 같은 사내망 질문 시, `data\vectordb`를 교차 탐색하여 정확한 규칙을 끌어냅니다.
- **PC 파일 검색**: "컴퓨터에서 2024년 기획서 파일 찾아줘" 등 검색 시, 내장된 Everything 엔진을 가동해 윈도우 로컬의 모든 파일을 찾아 UI 리스트로 던져줍니다.
- **일반 대화 및 코딩 멘토링**: 모든 행동은 마스터 페르소나를 기반으로 하며, 사용자와 자연스럽게 대화하며 지식 기반 응답을 생성합니다.

### 사용자 주의사항
- `Tavily` 등의 외부 검색 API Key가 지정되지 않으면 일반 검색 엔진은 비활성화됩니다. 단, **네이버 직접 스크래핑 기능이나 내부/파일 검색은 여전히 작동합니다.**
- Ollama 서버가 켜져 있지 않거나 사용할 모델(`OLLAMA_MODEL_NAME`)이 설치되어 있지 않으면 어시스턴트는 대답하지 못합니다.
- 초기 내부 문서 검색 구동을 위해서는 `data\model_cache`가 준비되어 있어야 하지만 기본 배포판은 이를 모두 포함하고 있습니다.
- PC 파일 검색은 윈도우 한경에서 구동되며 Everything 권한이 필요합니다.

---

## 💻 4. 개발자 가이드 (Developer Guide)

이 섹션은 소스코드를 직접 수정하고 운영하는 유지보수 개발자를 위한 영역입니다.

### 환경 변수(.env)와 민감 정보 파이프라인
프로젝트 루트의 `.env` 파일이 모든 기능을 중앙에서 통제합니다. GitHub 같은 퍼블릭 저장소에는 절대 올라가지 않습니다.

- `.env.example`은 Git에 포함되며, 뼈대 구조를 알려줍니다.
- 이 구조를 참고해 개인 PC에 `.env`를 만들어 사용합니다.

```env
TAVILY_API_KEY=여기에_실제_키_입력
OLLAMA_MODEL_NAME=llama3.1:8b
EVERYTHING_PORT=8888
RAG_COLLECTION_NAME=jarvis_docs
RAG_EMBEDDING_MODEL=paraphrase-multilingual-MiniLM-L12-v2
```

### 저장소 아키텍처 및 폴더 구조
```text
Root/
├── src/                  # 메인 소스 코드 구역
│   ├── app/              # 메인 윈도우 및 LLM 챗 워커 로직
│   ├── core/             # 라우팅 매니저, 경로 관리 등 코어 공통 코드
│   ├── services/         # Everything 파일 서치 훅, 네이버/Tavily 웹 스크래핑 모듈
│   ├── repositories/     # 채팅 로컬 JSON 저장소 계층
│   ├── ui/               # 말풍선(Bubbles), 마크다운 렌더러 등 PyQt5 디자인 위젯
│   └── rag/              # 임베딩/인덱싱 및 RAG 워커 전용 스크립트 모음
├── data/                 # 런타임 데이터 허브 (Git ignore 대상)
│   ├── documents/        # RAG용 오리지널 사내 PDF를 보관하는 장소
│   ├── vectordb/         # PDF 청크(Chunk)가 저장되는 Chroma DB 폴더
│   ├── model_cache/      # 인터넷 오프라인 지원용 SentenceTransformer 모델 캐시
│   └── chats/            # 사용자 채팅 히스토리
├── assets/               # 앱 아이콘, Everything 엔진 실행 파일 본체
├── scripts/              # jarvis.py 편의 스크립트 및 빌드(.bat) 파일 보관
└── packaging/            # PyInstaller Spec 및 런타임 DLL 훅 파일들
```

### 내부 문서(PDF) 수동 추가 및 Vector DB 업데이트
사내 문서 규칙이 개정되는 등 PDF 파일 속 내용이 바뀌었을 땐 다음을 수행해야 최신 데이터를 인지합니다.
1. `data\documents`에 갱신할 PDF 파일들을 넣습니다.
2. `venv\Scripts\python.exe src\rag\ingest.py` 구동 (기존 DB를 엎고 새로 벡터를 생성하는 작업)
3. `venv\Scripts\python.exe jarvis.py` 를 실행해 변경 사항이 정상적으로 반영되었는지 QA를 수행합니다.

---

## 📦 5. 최적화 및 배포 관리 (Deployment)

### 패키징(PyInstaller) 및 실행 파일(.exe) 빌드
현재 작동이 확인된 소스코드와 최신 RAG 벡터 데이터베이스, 무거운 내부 에셋 모범 파일들을 모조리 모아 단 한 방에 `.exe`로 압축합니다.

```powershell
scripts\build_jarvis.bat
```
빌드가 성공적으로 끝나면 `dist\jarvis\jarvis.exe` 가 단일로 생성되며, 최종 배포를 위해 `jarvis_package.zip`이라는 이름의 묶음이 프로젝트 최상단에 등장합니다!

### 캐시 최적화 및 빌드 속도를 높이는 꿀팁
앱 빌드 용량의 대부분(약 450MB)은 `data\model_cache`에 저장되는 오프라인 텍스트 임베딩 언어 모델 뭉치입니다. 인터넷 환경과 무관한 완벽한 100% 로컬 구동을 위해 기본 파이프라인에 이 캐시를 포함시켰습니다.

- `build` 폴더는 용량이 꽤 되지만 삭제하지 않는 것을 강력히 권합니다. (PyInstaller 분석 캐시를 살려두면 재빌드 시 시간이 어마어마하게 절약됩니다).
- `data\hf_cache`는 임시 다운로드이므로 `.gitignore` 처리되어 있어 배포 시 신경 쓰지 않으셔도 됩니다.
- 윈도우 디펜더 같은 백신이 `dist`나 `build` 폴더를 과하게 훑어보면 빌드 속도가 기하급수적으로 느려지니 검사 예외 등록을 고려해보세요.

---

## ❓ 6. 트러블슈팅 및 운영 (Troubleshooting)

### Q. Ollama가 아예 응답하지 않고 무한 대기합니다.
- 설치 여부와 `ollama pull [모델명]`을 터미널에서 올바르게 타이핑했는지 확인하세요.
- `.env` 파일 혹은 코드 내의 `OLLAMA_MODEL_NAME`과 실제 PC에 다운로드한 모델명이 매칭되는지 체크하세요.

### Q. '휴가 규정'을 물어봐도 딴소리를 합니다. (내부 문서 RAG 실패)
- `data\documents` 폴더 안에 실제로 PDF 문서가 존재하는지 눈으로 확인하세요.
- PDF를 수정한 이후, `src\rag\ingest.py` 스크립트를 실수로 까먹고 안 돌려서 과거 구식 벡터를 계속 참조하고 있을 확률이 제일 높습니다.

### Q. 'PC 파일 검색'을 시켰는데 프로그램 작동이 잘 안 됩니다.
- `assets\everything\Everything.exe` 본체가 해당 폴더에 제대로 있는지 파악하세요.
- 포트 충돌(`EVERYTHING_PORT`)이 발생하는지 `.env` 세팅을 점검하세요.

### Q. 실행 파이썬 빌드가 아예 깨붙지 않고 에러가 뜹니다.
- 이전 zip 파일이나 `dist` 경로의 `jarvis.exe`를 다른 창에 틀어두고 잠겨있는(Locking) 상태는 아닌지 확인하세요.

---
**💡 [권장 문서 교체 및 운영 프로세스 순서도]**
`1. PDF 버전 반영` ➡️ `2. ingest.py 벡터 스크립트 실행` ➡️ `3. 로컬 jarvis.py로 테스트 발송` ➡️ `4. 이상 발견 없을 시 build_jarvis.bat 가동` ➡️ `5. 완성된 zip을 사내 최종 배포`
