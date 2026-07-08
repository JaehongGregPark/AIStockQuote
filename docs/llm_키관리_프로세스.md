# LLM 키관리 프로세스

AIStockQuote의 AI 종목 해설 기능(Anthropic / OpenAI / Gemini)에 쓰이는 API 키를 등록·검증하는 절차를 정리한 운영 매뉴얼입니다. (LinguaUp `docs/llm_키관리_프로세스.md`와 동일한 포맷)

## 1. 키 저장 구조

LinguaUp(DB 우선, .env는 fallback)과 달리 이 프로젝트는 **DB가 없고 `.env` 파일 하나가 유일한 저장소**입니다 (`app/config.py`).

- 서버 시작 시 `find_dotenv()`로 실제 사용 중인 `.env` 경로를 찾아 그 경로를 `ENV_FILE_PATH`로 고정
- 관리자 화면(설정 탭)에서 키를 저장하면 `persist_env_value()`가 `python-dotenv`의 `set_key()`로 **같은 `.env` 파일에 즉시 기록**하고, 동시에 `config.ANTHROPIC_API_KEY` 등 인메모리 값도 갱신
- 즉 "DB 값과 .env 값이 다르다" 같은 혼선이 구조적으로 발생하지 않음 — 값은 항상 하나(`.env`)뿐이고 화면에 보이는 값과 파일 값이 항상 동기화됨

## 2. 키 등록 절차

1. 각 provider 콘솔에서 API 키 발급
2. 앱 실행 후 화면 상단 탭 중 **설정** 탭 진입
3. 해당 provider의 API Key / 모델명 입력 후 저장 → `POST /api/ai/config/{provider}` (`app/api/routes.py`)
   - 저장과 동시에 `.env`에 기록되고 즉시 반영됨 (재시작 불필요)
4. "테스트" 버튼 → 실제로 해당 provider에 최소 호출(`ai_analysis.check_provider`)을 보내 키/모델이 실제로 동작하는지 확인. 실패 시 그 키로 사용 가능한 모델 목록(`list_models`)도 같이 보여줌
5. 여러 provider 키를 동시에 넣은 경우 `AI_PROVIDER`를 명시하지 않으면 anthropic → openai → gemini 순으로 먼저 설정된 키가 자동 사용됨. **사용할 AI 제공자** 선택 UI로 명시적으로 고정 가능 (`POST /api/ai/active-provider`)

## 3. 저장된 값 확인 방법

- `GET /api/ai/status` — provider별로 실제 사용 가능 여부를 점검해 반환 (키 원문은 노출하지 않음)
- `.env` 파일을 직접 열어 확인 가능 (DB가 없으므로 이게 유일한 원본)

## 4. 환경 점검 결과 (2026-07-08 기준)

로컬 `.venv`와 요구사항을 점검한 결과, LinguaUp에서 겪었던 유형의 버전 호환성 문제는 **발견되지 않았습니다**.

| 항목 | 값 | 비고 |
|---|---|---|
| Python | 3.13.0 (`.venv`) | 최신 버전, `X \| Y` 타입힌트 관련 이슈 없음 |
| anthropic | 0.116.0 | `proxies` 인자 관련 구버전 버그 없음 |
| openai | 2.44.0 | |
| google-generativeai | 0.8.6 | LinguaUp이 쓰는 `google-genai`(신규 SDK)와는 다른 패키지. 별도 SDK라 `google-genai==0.5.0+`의 import-time 버그와 무관 |
| httpx | 0.28.1 | anthropic 0.116.0과 호환 (구버전 anthropic처럼 `proxies=`를 무조건 넘기지 않음) |

`requirements.txt`에 상한선(`<=`)이 없어 시간이 지나면 버전이 계속 최신으로 갱신됩니다. 향후 pip이 자동으로 끌어올린 조합에서 문제가 생기면, 이 표를 기준으로 "직전에 뭐가 바뀌었는지" 비교하는 용도로 활용하세요.

`pytest` 31개 테스트 전체 통과 확인 (`ai_analysis`, `config update`, `active provider`, `status timeout` 등 AI 키 관리 관련 테스트 포함).

## 5. 참고 — LinguaUp과의 구조 차이

| | LinguaUp | AIStockQuote |
|---|---|---|
| 저장소 | PostgreSQL(`AppSetting` 모델) | `.env` 파일 (DB 없음) |
| 우선순위 혼선 가능성 | 있음 (DB > .env, 관리자에서 안 바꾸면 안 됨) | 없음 (파일 하나뿐) |
| 로컬/운영 키 공유 | 안 됨 (DB가 서로 다름) | 배포 시 `.env`를 서버에 별도로 채워야 함 (구조는 같음) |
| Python 버전 제약 | 3.9 (운영 Docker) → `google-genai`/`anthropic` 구버전 이슈 있었음 | 제약 없음 (3.13), 현재 이슈 없음 |

배포 환경이 정해지면(예: LinguaUp처럼 Python 3.9 컨테이너로 옮길 경우) 이 표의 마지막 행을 다시 점검해야 합니다 — 특히 `anthropic`/`httpx` 조합은 상한선을 걸어두는 걸 권장합니다.
