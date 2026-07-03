# AiStockQuote

원래는 Kotlin/Jetpack Compose로 작성된 안드로이드 샘플 주식 시세 앱(StockQuoteApp)이었으나,
Python(FastAPI) 웹 애플리케이션으로 이식하면서 AI 종목 해설 기능을 추가했습니다.

## 기능

- KOSPI / KOSDAQ / NASDAQ / DOW 4개 시장, 시장별 상위 20개 종목 시세 조회
- 현재가, 등락, 등락률, 거래소, 통화, 최종 갱신 시각 표시
- 종목 상세: 1개월 가격 차트, 시가/고가/저가
- **AI 분석(신규)**: 선택한 종목의 등락과 최근 추세를 자연어로 요약 (Anthropic API 키 설정 시 활성화)
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
# .env 파일에 필요 시 ANTHROPIC_API_KEY 입력 (선택)

uvicorn app.main:app --reload
```

브라우저에서 http://localhost:8000 접속.

## API

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/markets` | 시장 목록 |
| GET | `/api/markets/{market_id}/quotes` | 시장별 시세 목록 (`?refresh=true`로 캐시 무시) |
| GET | `/api/quotes/{symbol}` | 종목 상세 + 1개월 차트 (`?market=`, `?refresh=true`) |
| GET | `/api/quotes/{symbol}/analysis` | AI 종목 해설 (`?market=`) |

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
