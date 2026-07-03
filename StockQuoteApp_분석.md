# StockQuoteApp 종합 분석

## 개요

Android Studio용 샘플 주식 시세 조회 앱. Kotlin + Jetpack Compose 기반이며, 총 8개 소스 파일, 약 1,100줄로 구성된 소규모 프로젝트다. KOSPI, KOSDAQ, NASDAQ, DOW 4개 시장별 상위 20개 종목의 시세를 Yahoo Finance 비공식 차트 API에서 가져와 목록과 상세(가격 차트 포함) 화면으로 보여준다.

빌드 환경은 AGP 8.5.2, Kotlin 1.9.24, Gradle 8.7, Java 17로 최신 툴체인을 사용하며 minSdk 24 / targetSdk 34로 설정되어 있다.

## 아키텍처

MVVM 패턴을 따르는 4계층 구조다.

- `StockModels.kt` — 데이터 모델(`StockQuote`, `ChartPoint` 등)과 시장별 종목 카탈로그(`StockCatalog`)를 정의. `changeAmount`, `changePercent`는 계산 프로퍼티로 깔끔하게 구현.
- `StockQuoteRepository.kt` — OkHttp로 Yahoo Finance 차트 엔드포인트를 호출하고 JSON을 파싱. `Result<T>`로 성공/실패를 명시적으로 감쌈.
- `StockQuoteViewModel.kt` — `mutableStateOf` 기반 단일 `StockUiState`로 상태를 관리하고, `viewModelScope` + `Dispatchers.IO`로 네트워크 호출을 처리.
- `ui/StockQuoteScreen.kt` — Compose UI 전체(목록, 상세 다이얼로그, 커스텀 가격 차트 Canvas)를 한 파일에 구현.

이 규모의 샘플 앱치고는 계층 분리가 명확하고 `Result` 기반 에러 처리, 단일 상태 홀더 패턴 등 최신 Compose 권장 관례를 잘 따르고 있다.

## 발견된 이슈

### 성능

- **시장 목록 조회가 순차 동기 호출** (`StockQuoteRepository.fetchQuotes`): 종목 20개를 `map`으로 하나씩 순서대로 HTTP 요청한다. 종목당 연결 10초/읽기 10초 타임아웃이 설정되어 있어, 응답이 느린 종목이 섞이면 화면 전체 로딩이 수십 초까지 걸릴 수 있다. `async`/`awaitAll`(또는 OkHttp 비동기 콜) 기반 병렬 호출로 바꾸면 체감 속도가 크게 개선된다.
- 종목 상세는 시장 전환/재선택 시마다 강제 재조회(`forceRefresh = true`)되며, 별도의 캐시 만료 전략이 없다.

### 안정성 / 데이터 정합성

- `fetchQuotes`에서 개별 종목 실패 시 `mapNotNull { runCatching {...}.getOrNull() }`로 조용히 드롭한다. 일부 종목만 실패해도 사용자에게 어떤 종목이 빠졌는지 전혀 알려주지 않는다.
- 네트워크 계층에 재시도(retry)/백오프 로직이 없고, 사용자가 수동으로 "Retry" 버튼을 눌러야 한다.
- 로컬 캐싱(Room, DataStore 등)이 전혀 없어 앱을 재시작할 때마다 모든 데이터를 다시 받아온다(샘플 앱 범위상 의도된 것으로 보이나, 실사용 시 아쉬운 부분).

### 데이터 소스

- README에 명시된 대로 Yahoo Finance 비공식 엔드포인트를 사용 중이며, API 키 없이 동작하지만 공식 SLA가 없어 요청 형식 변경이나 레이트 리밋에 취약하다. 프로덕션 전환 시 공식 유료 API로 교체가 필요하다.

### 코드 품질

- `StockQuoteScreen.kt`가 588줄로 UI 파일 하나에 목록/상세/차트/포맷터가 모두 몰려 있다. `QuoteListItem`, `PriceChartCard`, `InfoGrid` 등을 별도 파일로 분리하면 가독성과 프리뷰 재사용성이 좋아진다.
- 상승/하락 색상(`Color(0xFF0C7A43)`, `Color(0xFFB3261E)`)과 카드 배경(`Color.White`)이 `MaterialTheme`이 아닌 하드코딩 값이라, 다크 모드에서 배경은 어두워지는데 카드만 흰색으로 남는 등 테마 일관성이 깨질 수 있다.
- `StockQuoteViewModel`이 `StockQuoteRepository()`를 기본 인자로 직접 생성해 테스트 시 목(mock) 주입이 번거롭다. 인터페이스 추출 또는 간단한 팩토리 도입을 권장.
- **자동화 테스트가 전무하다.** `build.gradle.kts`에는 JUnit/Espresso/Compose 테스트 의존성이 선언되어 있지만, 실제 `test`/`androidTest` 소스 디렉터리와 테스트 파일이 프로젝트에 존재하지 않는다. 특히 `StockQuoteRepository`의 JSON 파싱 로직(`lastNonNullDouble`, `previousNonNullDouble` 등 null 처리 분기)은 단위 테스트로 검증할 가치가 높다.

### 빌드/설정

- `release` 빌드 타입에서 `isMinifyEnabled = false`로 되어 있어 코드 축소/난독화가 적용되지 않는다. `proguard-rules.pro` 파일은 존재하지만 실질적으로 사용되지 않는 상태.
- 앱 아이콘(`mipmap`) 리소스가 없어 시스템 기본 아이콘으로 표시된다(샘플 앱이라 큰 문제는 아니지만 배포 전 커스텀 아이콘 추가가 필요).

## 개선 제안 우선순위

1. **(성능, 높음)** 시장 목록 조회를 `coroutineScope { symbols.map { async { ... } }.awaitAll() }` 형태로 병렬화.
2. **(품질, 높음)** `StockQuoteRepository` 파싱 로직에 대한 JUnit 단위 테스트 추가 — 리스크가 가장 큰 부분(JSON null 처리, 예외 경로)부터 커버.
3. **(UX, 중간)** 일부 종목 조회 실패 시 무시하지 말고 "N개 종목 로드 실패" 같은 부분 실패 안내 추가.
4. **(코드 구조, 중간)** `StockQuoteScreen.kt`를 `components/`, `formatting/` 등으로 분리.
5. **(테마, 낮음)** 하드코딩된 색상을 `MaterialTheme.colorScheme` 커스텀 컬러로 이전해 다크 모드 대응.
6. **(배포 준비, 낮음)** release 빌드 `minifyEnabled = true` 적용 및 앱 아이콘 추가.

## 결론

전형적인 "잘 만든 샘플 앱" 수준으로, MVVM 구조와 Compose 활용은 깔끔하다. 다만 순차적 네트워크 호출로 인한 체감 성능 저하, 테스트 부재, 부분 실패 시 무음 처리가 가장 눈에 띄는 개선 지점이다. 실제 배포용 앱으로 발전시키려면 데이터 소스를 공식 API로 교체하고 캐싱/재시도 전략을 보강하는 것이 우선이다.
