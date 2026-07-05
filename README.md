# AiStockQuote

원래는 Kotlin/Jetpack Compose로 작성된 안드로이드 샘플 주식 시세 앱(StockQuoteApp)이었으나,
Python(FastAPI) 웹 애플리케이션으로 이식하면서 AI 종목 해설 기능을 추가했습니다.

## 기능

- KOSPI / KOSDAQ / NASDAQ / DOW 4개 시장, 시장별 상위 20개 종목 시세 조회
- 현재가, 등락, 등락률, 거래소, 통화, 최종 갱신 시각 표시
- 종목 상세: 1개월 가격 차트, 시가/고가/저가
- **AI 분석(신규)**: 선택한 종목의 등락과 최근 추세를 자연어로 요약 (Anthropic / OpenAI / Gemini 중 하나의 API 키 설정 시 활성화)
- 일부 종목 조회 실패 시 무음 처리 대신 실패 종목 목록을 함께 반환

## 기술 스택

- 백엔드: FastAPI, yfinance, Pydantic
- 프론트엔드: 정적 HTML/CSS/JS + Chart.js (빌드 도구 불필요)
- AI: Anthropic API (선택)
- 테스트: pytest, pytest-asyncio

## 설치 및 실행

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# .env 파일에 ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY 중
# 하나 이상 입력 (선택)

uvicorn app.main:app --reload
```

브라우저에서 http://localhost:8000 접속.

### AI 제공자 설정

`.env`에 아래 키 중 하나 이상을 입력하면 AI 분석 기능이 활성화됩니다.

| 변수 | 설명 |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic Claude 사용 |
| `OPENAI_API_KEY` | OpenAI 사용 |
| `GEMINI_API_KEY` | Google Gemini 사용 |
| `AI_PROVIDER` | `anthropic` \| `openai` \| `gemini` 중 명시적 지정 (선택, 비워두면 위 순서로 자동 선택) |
| `ANTHROPIC_MODEL` / `OPENAI_MODEL` / `GEMINI_MODEL` | 제공자별 모델명 오버라이드 (선택) |

여러 키를 동시에 설정한 경우 `AI_PROVIDER`를 지정하지 않으면
Anthropic → OpenAI → Gemini 순서로 첫 번째로 설정된 키를 사용합니다.

화면 상단 탭의 맨 마지막 **설정** 탭에서도 GUI로 구성할 수 있습니다.

- **AI 제공자 API 키 / 모델**: anthropic/openai/gemini 각각 API 키·모델을 입력하고
  "테스트"를 누르면 실제로 호출해 사용 가능 여부를 보여주고, 입력값을 즉시 반영 +
  `.env`에도 기록합니다 (기존에 있던 다른 줄이나 주석은 그대로 유지).
- **사용할 AI 제공자**: 3개 제공자 중 하나(또는 자동)를 선택해 저장하면, 이후
  `/api/quotes/{symbol}/analysis`가 그 제공자의 키·모델로 AI 분석을 수행합니다.

## API

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/markets` | 시장 목록 |
| GET | `/api/markets/{market_id}/quotes` | 시장별 시세 목록 (`?refresh=true`로 캐시 무시) |
| GET | `/api/quotes/{symbol}` | 종목 상세 + 1개월 차트 (`?market=`, `?refresh=true`) |
| GET | `/api/quotes/{symbol}/analysis` | AI 종목 해설 (`?market=`) |
| GET | `/api/ai/status` | provider별(anthropic/openai/gemini) API 키·모델 상태 실제 점검, 현재 사용 중인 provider 표시 |
| POST | `/api/ai/config/{provider}` | 해당 provider의 API 키/모델을 설정 — 즉시 반영 + `.env`에도 기록 (`{"api_key": "...", "model": "..."}`) |
| POST | `/api/ai/active-provider` | AI 분석에 사용할 provider 지정 — `{"provider": "openai"}`, `null`이면 자동 우선순위로 복귀 |

## 데이터 소스

`yfinance` 라이브러리를 통해 Yahoo Finance 데이터를 사용합니다. 무료 비공식 데이터이므로
프로덕션 환경에서는 공식 유료 시세 API로 교체를 검토하세요.

## 테스트

```bash
pytest
```

## 원본 안드로이드 프로젝트 대비 개선 사항

- 시장 목록 조회를 스레드 풀 기반으로 병렬화 (기존: 종목별 순차 동기 호출)
- 서버 사이드 TTL 캐시로 반복 요청 부담 감소
- 일부 종목 조회 실패 시 실패 목록을 응답에 포함 (기존: 무음 드롭)
- repository/service 계층에 대한 pytest 단위 테스트 추가 (기존: 테스트 없음)
