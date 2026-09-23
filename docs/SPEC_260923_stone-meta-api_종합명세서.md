# stone-meta-api 종합 API 명세서 (data_decision · query_execute · meta · health)

| 항목 | 값 |
|---|---|
| 문서 상태 | 정본 (v1.1 - GET /health 원천별 메타 갱신시각 및 동기화 계약 확장 개정판) |
| 기준일 | 2026-09-23 |
| 이전 버전 | `SPEC_260922_stone-meta-api_종합명세서.md` |
| 대상 서비스 | K-AIR-Stone `stone-meta-api` |
| 지원 경로 | `GET /health`, `POST /data_decision`, `POST /query_execute`, `POST /t2sql`<br>`POST /meta/catalog`, `POST /meta/table`, `POST /meta/column`, `POST /meta/ref`, `POST /meta/fk`, `POST /meta/batch`<br>진단: `GET /meta/coverage`, `POST /meta/table/graph`<br>폐기(410): `POST /semantic_decision`, `POST /query/execute` |
| 계약 정본 | `K-AIR-Stone/backend/services/stone_meta/contract.py` |
| 라우터 구현 | `K-AIR-Stone/backend/routers/stone_meta_api.py` |
| 메타 서비스 | `K-AIR-Stone/backend/services/stone_meta/meta_service.py` |
| 쿼리 실행기 | `K-AIR-Stone/backend/services/stone_meta/execute.py` |
| 헬스 서비스 | `K-AIR-Stone/backend/services/stone_meta/health.py` |
| 계약 버전 | `meta_version: "1.0"` (응답 헤더 `X-Meta-Version: 1.0` 상시 동봉) |

---

## 1. 개요 및 아키텍처

`stone-meta-api`는 K-AIR 플랫폼에서 자연어 질의 분석, 메타데이터 서빙, 결정론적 SQL 생성 및 안전한 쿼리 실행을 전담하는 핵심 백엔드 서비스입니다.
기존 `robo-meta-api`의 9대 계약 인터페이스를 바이트 단위 호환성(Parity)을 유지하면서 계승하고, 다중 데이터소스 바인딩, 스냅샷 승인 거버넌스, 근거(Provenance) 추적, 파티션/인덱스 힌트 등의 엔터프라이즈 기능을 확장하여 제공합니다.

특히 **v1.1 개정판(2026-09-23)**에서는 클라이언트(MCP 서버, 로컬 LLM 에이전트 등)가 상시 메타데이터를 전량 다운로드하지 않고, `GET /health`를 통해 각 데이터소스별 메타데이터 갱신 시각(`updated_at`) 및 스냅샷 변경을 감지하여 변경된 원천에 대해서만 선별적으로 `/meta/*` API를 호출하는 **조건부 증분 메타 동기화 아키텍처**를 공식 규격으로 채택하였습니다.

### 1.1 전체 엔드포인트 일람

| 분류 | HTTP 메서드 및 경로 | 설명 | 주요 입/출력 모델 |
|---|---|---|---|
| **진단/동기화** | `GET /health` | 메타데이터 저장소 헬스체크 및 원천별 활성 스냅샷/갱신시각(`sources[]`) 반환 | `HealthResponse` |
| **의사결정** | `POST /data_decision` | 자연어 질문 기반 테이블/컬럼 후보 추천, 온톨로지 매핑, 엔티티 해소 | `DecisionRequest` → `DecisionResponse` |
| **쿼리실행** | `POST /query_execute` | 검증된 읽기 전용 SQL 실행 (가드, 타임아웃, 2단/3단 식별자 해석) | `QueryExecuteRequest` → `QueryExecuteResponse` |
| **메타서빙**<br>(핵심) | `POST /meta/catalog` | 서빙 테이블 목록 전량(컬럼·FK 포함) 또는 Keyset 페이징 조회 | `CatalogRequest` → `CatalogResponse` |
| | `POST /meta/table` | 단일 테이블의 상세 메타데이터 (컬럼, FK, 거버넌스, 리니지, 앵커) | `TableKey` → `MetaTableResponse` |
| | `POST /meta/column` | 단일 컬럼의 상세 메타데이터 (데이터타입, 제약, 코드사전, 용어매핑) | `ColumnRequest` → `MetaColumnResponse` |
| | `POST /meta/ref` | 테이블의 외래키(FK) 참조 관계 목록 조회 | `TableKey` → `MetaRefResponse` |
| | `POST /meta/fk` | `/meta/ref`의 레거시 호환 별칭 (동일 동작) | `TableKey` → `MetaRefResponse` |
| | `POST /meta/batch` | 배치 단위 카탈로그 테이블 목록 조회 (Keyset 페이징 지원) | `BatchRequest` → `BatchResponse` |
| **SQL생성** | `POST /t2sql` | 자연어 기반 결정론적 읽기 SQL 생성 (LLM 0회 호출 보장) | `T2SqlRequest` → `T2SqlResponse` |
| **진단/분석** | `GET /meta/coverage` | 메타데이터 슬롯별 채움률 리포트 (온톨로지, 리니지, 근거 채움률) | `CoverageReport` |
| | `POST /meta/table/graph` | 스냅샷 대 라이브 Neo4j 그래프 드리프트 대조 리포트 | `TableKey` → `GraphDriftReport` |
| **폐기안내** | `POST /semantic_decision`<br>`POST /query/execute` | 구버전 호출 클라이언트를 위한 410 Gone 스텁 안내 경로 | 410 Gone 반환 |

### 1.2 호출 창구 및 네트워크 구성

| 창구 형태 | Base URL | 비고 |
|---|---|---|
| **단독 컨테이너 직접 접속** | `http://<host>:8096` | 내부 마이크로서비스 및 MCP 간 직접 호출 포트 |
| **stone-meta-proxy (Nginx)** | `http://<host>:8111` 또는 `http://<host>:8096` | 리버스 프록시 및 게이트웨이 경유 |
| **nk-backend 마운트** | `http://<host>:<port>/air-swmm/stone-meta` | 백엔드 서브라우터 마운트 호환 경로 |

### 1.3 공통 규격 및 에러 처리

1. **응답 헤더**:
   - 모든 정상 응답 및 오류 응답에는 `X-Meta-Version: 1.0` 헤더가 항상 포함됩니다.
2. **에러 응답 본문**:
   - FastAPI 표준 에러 규격인 `{"detail": ...}` 형태로 반환됩니다.
   - `400 Bad Request`: 요청 파라미터 유효성 검증 실패, 잘못된 SQL 구문, 깨진 페이징 커서(`cursor`) 등.
   - `404 Not Found`: 대상 테이블(`table not found`) 또는 컬럼(`column not found`)이 메타 저장소에 없음.
   - `410 Gone`: 폐기된 엔드포인트 호출 또는 폐기된 파라미터(`artifact_id`) 지정 시 대체 경로 안내.
   - `503 Service Unavailable`: 메타데이터 저장소(PostgreSQL/Neo4j) 불통 시 4요소(컴포넌트/대상/작업/조치) 진단 로깅과 함께 사용자 안내 메시지 반환.
3. **Scope (조회 범위)**:
   - `all` (기본값): 필터 없이 저장소에 적재된 모든 메타데이터를 조회합니다.
   - `serving`: 승인(`review_status='approved'`), 유효(`text_to_sql_is_valid=true`), 활성 스냅샷에 포함된 테이블/컬럼만 한정 조회합니다.

---

## 2. GET /health (헬스체크 및 원천별 메타 동기화 판정)

`GET /health`는 메타데이터 저장소의 정상 가동 여부를 확인하는 동시에, 연결된 각 데이터소스별 활성 스냅샷 정보와 **메타데이터 생성/수정 일시(`updated_at`)**를 반환합니다.

### 2.1 수신 측(MCP / Agent) 메타 동기화 패턴

수신 측 서비스는 대량의 트래픽을 유발하는 `/meta/*` 전량 호출을 상시 수행하지 않고, 다음과 같은 캐시 대조 절차를 권장합니다:

```
[클라이언트 / MCP 서버]                             [stone-meta-api]
         │                                                 │
         │ 1. GET /health 호출                             │
         ├────────────────────────────────────────────────>│
         │                                                 │
         │ 2. sources[] (원천별 updated_at / generation) 반환│
         │<────────────────────────────────────────────────┤
         │                                                 │
   [로컬 캐시 대조]                                        │
   - 로컬에 기록된 source_instance_id의 updated_at과 비교    │
   - 일치함: 메타 변경 없음 → 로컬 캐시 유지               │
   - 불일치/신규: 메타 갱신 감지!                           │
         │                                                 │
         │ 3. 변경된 원천만 선별 동기화                      │
         │    POST /meta/catalog 또는 POST /meta/table      │
         ├────────────────────────────────────────────────>│
         │                                                 │
         │ 4. 신규 메타데이터 수신 및 로컬 캐시 갱신         │
         │<────────────────────────────────────────────────┤
```

### 2.2 응답 규격 (`HealthResponse`)

| 필드명 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `version` | string | **예** | API 서버 소프트웨어 버전 (예: `"1.0.0"`) |
| `meta_version` | string | **예** | 계약 버전 (`"1.0"`) |
| `status` | string | **예** | 서버 상태 (`"ok"` \| `"degraded"` \| `"error"`) |
| `metadata_backend` | string | **예** | 메타데이터 저장소 백엔드 종류 (`"postgres"`) |
| `execution_backend` | string | **예** | 쿼리 실행 엔진 백엔드 종류 (`"mindsdb"`) |
| `t2sql_configured` | bool | **예** | Text-to-SQL 파이프라인 구성 완료 여부 |
| `source_binding_count` | int | **예** | 연결된 활성 데이터소스 수 |
| `source_instance_ids` | string[] | **예** | 연결된 데이터소스 식별자 목록 (예: `["RWIS"]`) |
| `sources` | `HealthSourceItem[]` | 아니오 | 각 데이터소스별 활성 스냅샷 및 갱신 일시 상세 목록 |

#### `HealthSourceItem` 구조체

| 필드명 | 타입 | 설명 |
|---|---|---|
| `source_instance_id` | string | 데이터소스 고유 식별자 (예: `"RWIS"`) |
| `snapshot_id` | string \| null | 현재 활성화된 메타 스냅샷 식별자 (예: `"stone:RWIS:g1"`) |
| `generation` | int \| null | 스냅샷 세대 번호 (예: `1`) |
| `updated_at` | string \| null | 메타데이터 활성화/갱신 일시 (ISO-8601 UTC, 예: `"2026-09-15T10:56:51.378995+00:00"`) |

### 2.3 실제 응답 예시 (HTTP 200)

```json
{
  "version": "1.0.0",
  "meta_version": "1.0",
  "status": "ok",
  "metadata_backend": "postgres",
  "execution_backend": "mindsdb",
  "t2sql_configured": true,
  "source_binding_count": 1,
  "source_instance_ids": [
    "RWIS"
  ],
  "sources": [
    {
      "source_instance_id": "RWIS",
      "snapshot_id": "stone:RWIS:g1",
      "generation": 1,
      "updated_at": "2026-09-15T10:56:51.378995+00:00"
    }
  ]
}
```

---

## 3. POST /data_decision (메타 의사결정)

자연어 질의를 분석하여 가장 적합한 테이블 후보군(Top-K), 컬럼 매칭 정보, 온톨로지 앵커 및 검수된 사전 기반 엔티티 해소 결과를 종합하여 반환합니다.

### 3.1 요청 규격 (`DecisionRequest`)

| 필드명 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `query` | string (min 1) | **예** | — | 사용자의 자연어 검색 질의 (예: `"화성정수장 최근 일주일간 탁도 평균"`) |
| `include_matched_columns`| bool | 아니오 | `true` | `false` 지정 시 `candidates[].matched_columns`를 빈 배열로 반환 |
| `column_top_m` | int (1~50) \| null | 아니오 | `10` | 테이블별 벡터/어휘 매칭 컬럼 상한 |
| `table_limit` | int (1~50) \| null | 아니오 | `10` | 추천 테이블 후보 상한 (Top-K) |
| `auto_resolve_entities` | bool | 아니오 | `true` | 시설, 태그, 코드사전 기반 엔티티 자동 해소 수행 여부 |
| `source_instance_id` | string \| null | 아니오 | `null` | 특정 데이터소스로 탐색 범위 한정 (지정하지 않으면 전 원천 탐색) |

### 3.2 응답 규격 (`DecisionResponse`)

최상위 15대 필드로 구성됩니다:

| 필드명 | 타입 | 설명 |
|---|---|---|
| `meta_version` | string | 계약 버전 (`"1.0"`) |
| `target` | enum | 1위 후보 표의 데이터 계층 분류 (`analytic` \| `source` \| `collect` \| `none`) |
| `secondary_targets` | string[] | 차순위 타깃 계층 목록 (`analytic` → `source` → `collect`) |
| `confidence` | float | 신뢰도 (후보 표 존재 시 `1.0`, 전혀 없으면 `0.0`) |
| `candidates` | `DecisionCandidate[]` | 추천 테이블 후보 목록 (Top-K 랭킹) |
| `join_groups` | `JoinGroup[]` | 직접 FK 기반 조인 가능한 테이블 묶음 |
| `threshold_used` | object | 검색, 온톨로지 지문, 원천 바인딩 진단 정보 |
| `resolved_entities` | `ResolvedEntity[]` | 질문에서 자동 해소된 개체 (시설, 계측 태그, 코드 등) |
| `suggested_probes` | `SuggestedProbe[]` | 코드 조회 제안 쿼리 목록 |
| `resolution_status` | enum | 엔티티 해소 상태 (`complete` \| `partial` \| `skipped` \| `failed`) |
| `execution_context` | `ExecutionContext` \| null | 단일 데이터소스로 확정된 경우 실행 접속 컨텍스트 |
| `query_analysis` | `QueryAnalysis` \| null | LLM 질의 분석 결과 객체 |
| `query_plan` | `QueryPlan` \| null | 계획된 조인 경로, 사전 필터(`PlannedFilter`), 후보 선정 근거 |
| `glossary_routes` | `GlossaryRoute[]` | 질문 내 언급어와 표준용어 사전 매핑 경로 |
| `universal_plan` | `UniversalServingPlan` \| null | 범용 엔티티-메트릭 서빙 플랜 |

#### 주요 하위 구조체

- **`DecisionCandidate`**:
  - `db`, `schema_name`, `table_name`: 물리 테이블 식별자.
  - `score`: 매칭 점수 (0.0 ~ 1.0).
  - `target_class`, `subject_area`: 계층 및 업무 영역 분류 (`agg`, `raw`, `code`, `hist`, `master`, `link`, `unknown`).
  - `table_name_kr`, `logical_name`: 승인 한글 논리명.
  - `description`, `table_comment`: 테이블 상세 설명.
  - `time_column`: 대표 시간 컬럼명 (예: `"LOG_TIME"`).
  - `latest_data_time`: 메타에 기록된 최종 적재 시각 (예: `"2026-02-09 24:00"`).
  - `partition_key`, `index_columns`: 원천 DB 물리 인덱스 및 파티션 컬럼 목록.
  - `matched_columns`: 매칭된 컬럼 상세 목록 (`column_name`, `score`, `column_name_kr`, `data_type`, `constraints`, `has_code`, `provenance`).
- **`threshold_used`**:
  - `table_top_k`, `column_top_m`: 적용된 상한치.
  - `retrieval_axes`: 적용된 4대 검색 축 (`["meta_context", "store", "standard_word_decomposition", "surface_contains"]`).
  - `mention_tokens`: 질문에서 추출된 형태소/표준단어 토큰.
  - `meta_context`: 온톨로지 코어 판정 지문 (`fingerprint`, `datasource_scope_skipped` 등).
  - `execution_binding`: 바인딩 결과 (`status`, `reason_key`, `source_instance_id`, `candidates`).

---

## 4. POST /query_execute (안전한 읽기 전용 쿼리 실행)

MindsDB 및 원천 데이터베이스를 경유하여 읽기 전용 쿼리를 안전하게 실행하고 결과를 표 형태로 반환합니다.

### 4.1 안전 가드 및 실행 제약

- **읽기 전용 가드**: `SELECT`, `WITH`, `EXPLAIN`(ANALYZE 제외), `SHOW` 문만 허용합니다. `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `GRANT`, 세션 변경 등 모든 변경/관리 구문은 `400 Bad Request`로 즉각 차단됩니다.
- **다중 구문 금지**: 세미콜론(`;`)으로 연결된 다중 쿼리 실행은 허용되지 않습니다.
- **실행 시간 제한**: `timeout_s`는 1~120초 범위이며, 기본값은 10초입니다.
- **반환 행수 제한**: `max_rows`는 1~100,000 범위로 요청 가능하나, 서버 절대 상한은 10,000행입니다 (기본 1,000행).
- **식별자 해석 규칙**:
  - 3단 표기: `` `SourceName`.`Schema`.`Table` `` (플랫폼 연결 소스명 권장)
  - 2단 표기: `` `Schema`.`Table` `` (`allowed_schemas` 또는 단일 소스 자동 바인딩)
  - MindsDB 내부 UUID 카탈로그는 노출되지 않고 플랫폼 소스 표시명으로 치환됩니다.

### 4.2 요청 규격 (`QueryExecuteRequest`)

| 필드명 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `sql` | string | **예** | — | 실행할 읽기 전용 SQL (예: ``SELECT * FROM `RWIS`.`RWIS`.`RDF01HH_TB` LIMIT 5``) |
| `execution_context` | `ExecutionContext` \| null | 아니오 | `null` | `/data_decision`에서 반환된 실행 컨텍스트. 미지정 시 SQL 구문의 식별자에서 자동 해석 |
| `timeout_s` | int (1~120) \| null | 아니오 | `10` | 쿼리 타임아웃 (초 단위) |
| `max_rows` | int (1~100000) \| null | 아니오 | `1000` | 최대 반환 행수 |
| `fingerprint` | string \| null | 아니오 | `null` | `/t2sql`에서 발급한 `sql_fingerprint`. 지정 시 SQL 위변조 검증 수행 |
| `artifact_id` | string \| null | **금지** | `null` | 폐기된 파라미터. 지정 시 `410 SEMANTIC_ARTIFACT_GONE` 오류 반환 |

### 4.3 응답 규격 (`QueryExecuteResponse`)

| 필드명 | 타입 | 설명 |
|---|---|---|
| `meta_version` | string | 계약 버전 (`"1.0"`) |
| `audit_id` | string | 실행 감사 추적용 UUID |
| `status` | enum | 실행 상태 (`ok` \| `timeout` \| `db_error` \| `error` \| `rejected`) |
| `error` | string \| null | 실패 시 에러 메시지 (성공 시 `null`) |
| `sql_executed` | string | 실제 원천에 전달되어 실행된 SQL 구문 |
| `columns` | string[] | 조회 결과 컬럼명 배열 |
| `rows` | any[][] | 행 단위 결과 데이터 (2차원 배열) |
| `row_count` | int | 실제 반환된 행 수 |
| `truncated` | bool | `max_rows`에 의해 결과가 잘렸는지 여부 |
| `elapsed_ms` | float | 실행 소요 시간 (밀리초) |
| `timeout_s_applied` | int | 적용된 타임아웃 초 |
| `max_rows_applied` | int | 적용된 행 상한 |
| `datasource` | string \| null | 실행 대상 원천 데이터소스 식별자 |
| `query_id` | string \| null | 백엔드 엔진 쿼리 식별자 |

---

## 5. 메타데이터 핵심 엔드포인트군 (/meta/*)

`stone-meta-api`의 메타데이터 서빙 엔드포인트들은 **완전 결정론적(Deterministic)**으로 동작합니다.
LLM이나 벡터 유사도 개입 없이, 승인된 메타데이터 스냅샷 저장소의 정합 데이터를 일관된 정렬 순서로 제공합니다.

```
                  ┌──────────────────────┐
                  │  POST /meta/catalog  │ (전체 카탈로그 개요 / 페이징)
                  └──────────┬───────────┘
                             │
            ┌────────────────┴────────────────┐
            ▼                                 ▼
┌──────────────────────┐           ┌──────────────────────┐
│   POST /meta/table   │           │   POST /meta/batch   │ (배치 카탈로그)
└───────────┬──────────┘           └──────────────────────┘
            │
      ┌─────┴─────────────────────────────────┐
      ▼                                       ▼
┌──────────────────────┐           ┌──────────────────────┐
│  POST /meta/column   │           │   POST /meta/ref     │ (외래키 관계)
└──────────────────────┘           └──────────────────────┘
```

---

### 5.1 POST /meta/catalog (서빙 카탈로그 목록 및 페이징)

서빙 승인된 데이터소스, 테이블, 컬럼 및 참조 관계를 일괄 조회하거나 Keyset 커서 페이징으로 탐색합니다.

#### 동작 모드
1. **전량 덤프 모드 (Full Dump)**:
   - 본문 생략(`{}`) 또는 `limit` 미지정 시 동작합니다.
   - 캐시 TTL이 적용된 원천별 카탈로그를 기반으로 모든 소스, 테이블, 컬럼, 외래키 참조(`references`), 역참조(`referenced_by`)를 완전하게 조립하여 반환합니다.
2. **이름 페이징 모드 (Keyset Pagination)**:
   - `limit` (1~200) 또는 이전 응답의 `cursor`를 지정하여 호출합니다.
   - 대규모 테이블 환경에서 CPU 부하를 방지하기 위해 **테이블 이름과 기본 속성 중심**의 한 페이지 목록을 빠르게 반환합니다. 컬럼 세부 메타는 `/meta/table` 또는 `/meta/column`을 통해 조회합니다.

#### 요청 규격 (`CatalogRequest`)

```json
{
  "source_instance_id": "RWIS",
  "limit": 50,
  "cursor": null
}
```

| 필드명 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `source_instance_id` | string \| null | 아니오 | `null` | 특정 데이터소스로 한정 조회 (GET /health의 id 값). 미지정 시 전 원천 |
| `limit` | int (1~200) \| null | 아니오 | `null` | 한 페이지 최대 테이블 수. 지정 시 페이징 모드, 미지정 시 전량 모드 |
| `cursor` | string \| null | 아니오 | `null` | 이전 응답의 `next_cursor` (Keyset 기반 커서) |

#### 응답 규격 (`CatalogResponse`)

```json
{
  "meta_version": "1.0",
  "serving_status": "active",
  "sources": [
    {
      "source_name": "RWIS",
      "engine": "tibero",
      "source_schema": "RWIS",
      "registered_at": "2026-04-20 10:00:00",
      "tables": [
        {
          "table_name": "RDF01HH_TB",
          "schema_name": "RWIS",
          "logical_name": "시간 데이터",
          "comment": "시간 데이터",
          "description": "시간별 계측 팩트 테이블",
          "row_count": 15420000,
          "subject_area": "raw",
          "columns": [
            {
              "column_name": "TAGSN",
              "data_type": "NUMBER(10)",
              "nullable": false,
              "primary_key": true,
              "logical_name": "태그일련번호",
              "comment": "태그 일련번호"
            }
          ],
          "references": [
            {
              "fk_name": "FK_RDF01HH_TAG",
              "source_column": "TAGSN",
              "target_schema": "RWIS",
              "target_table": "RDITAG_TB",
              "target_column": "TAGSN"
            }
          ],
          "referenced_by": []
        }
      ]
    }
  ]
}
```

---

### 5.2 POST /meta/table (단일 테이블 상세 메타데이터)

지정된 테이블의 심층 메타데이터(컬럼 목록, 파티션/인덱스 정보, 시간축 컬럼, 최신 적재 시각, 외래키 참조 관계, 거버넌스 승인 상태)를 조회합니다.

#### 요청 규격 (`TableKey`)

```json
{
  "schema_name": "RWIS",
  "table_name": "RDF01HH_TB",
  "db": "RWIS",
  "source_name": "RWIS",
  "scope": "serving"
}
```

| 필드명 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `schema_name` | string | **예** | — | 대상 스키마명 |
| `table_name` | string | **예** | — | 대상 테이블명 |
| `source_name` | string \| null | 아니오 | `null` | 데이터소스 명칭 (생략 시 자동 매칭) |
| `db` | string \| null | 아니오 | `null` | 원천 데이터베이스 라벨 |
| `scope` | enum | 아니오 | `"all"` | `"all"` 또는 `"serving"` |

#### 응답 규격 (`MetaTableResponse`)

```json
{
  "meta_version": "1.0",
  "table": {
    "db": "RWIS",
    "schema_name": "RWIS",
    "table_name": "RDF01HH_TB",
    "table_name_kr": "시간 데이터",
    "table_comment": "시간 데이터",
    "description": "시간별 계측 팩트 테이블",
    "subject_area": "raw",
    "table_type": "TABLE",
    "row_count": 15420000,
    "time_column": "LOG_TIME",
    "latest_data_time": "2026-02-09 24:00",
    "partition_key": "LOG_TIME",
    "index_columns": ["TAGSN", "LOG_TIME"],
    "review_status": "approved",
    "text_to_sql_is_valid": true,
    "columns": [
      {
        "column_name": "TAGSN",
        "column_name_kr": "태그일련번호",
        "data_type": "NUMBER(10)",
        "column_comment": "태그 일련번호",
        "description": "수질 계측 태그 마스터 일련번호 (PK/FK)",
        "constraints": ["PK", "FK"],
        "is_null": false,
        "nullability": "not_null",
        "column_is_active": "Y",
        "pk_ordinal": 1,
        "has_code": "Y",
        "has_code_status": "licensed",
        "code_lookup": {
          "ref_schema_name": "RWIS",
          "ref_table_name": "RDITAG_TB",
          "ref_column_name": "TAGSN",
          "via": "fk"
        },
        "term_mapping": {
          "standard_term": "태그일련번호",
          "physical_name": "TAGSN",
          "synonyms": ["태그번호", "TAG_NO"]
        },
        "value_examples": ["10001", "10002", "10003"],
        "provenance": {
          "label_ko": {
            "origin": "standard_term",
            "match_kind": "exact",
            "confidence": 1.0,
            "grade": "canonical"
          }
        }
      }
    ]
  },
  "fk": [
    {
      "column_name": "TAGSN",
      "position": 1,
      "ref_schema_name": "RWIS",
      "ref_table_name": "RDITAG_TB",
      "ref_column_name": "TAGSN"
    }
  ]
}
```

#### 세부 필드 설명

1. **`time_column` & `latest_data_time`**:
   - `time_column`: 해당 테이블의 대표 시간축 컬럼 (예: `LOG_TIME`). 기간 필터 생성의 기준입니다.
   - `latest_data_time`: 시스템 벽시계(Wall clock)가 아닌, 실제 데이터가 저장소에 적재된 최신 시각입니다. "최근 7일"과 같은 상대기간 쿼리 생성 시 데이터 절단(0건 반환)을 방지하는 앵커로 작동합니다.
2. **`nullability` 3값 체계**:
   - `is_null` boolean 값은 미상 데이터를 `false`(NOT NULL)로 왜곡할 위험이 있습니다.
   - `nullability`는 `"nullable"`, `"not_null"`, `"unknown"`(미상)의 3가지 상태를 정직하게 명시합니다.
3. **`has_code_status`**:
   - `has_code="N"`이 실제로 코드 컬럼이 아닌지, 검수 미승인으로 평가되지 않은 것인지를 `has_code_status`(`"licensed"`, `"none"`, `"not_evaluated"`)로 구별합니다.
4. **`provenance` (근거 4요소)**:
   - 한글명/설명이 어디서 유래했는지 추적: `origin`(출처: `standard_term`, `ddl`, `robo:llm`), `match_kind`(매칭 방식: `exact`, `word_partial`), `confidence`(정확도 수치), `grade`(`canonical` 공인, `authored` 작성, `inferred` 추론, `unknown` 미상).

---

### 5.3 POST /meta/column (단일 컬럼 상세 메타데이터)

테이블 내 특정 단일 컬럼에 대한 상세 메타데이터를 조회합니다.

#### 요청 규격 (`ColumnRequest`)

```json
{
  "schema_name": "RWIS",
  "table_name": "RDF01HH_TB",
  "column_name": "TAGSN",
  "db": "RWIS",
  "scope": "serving"
}
```

| 필드명 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `schema_name` | string | **예** | — | 대상 스키마명 |
| `table_name` | string | **예** | — | 대상 테이블명 |
| `column_name` | string | **예** | — | 조회할 컬럼명 |
| `source_name` | string \| null | 아니오 | `null` | 데이터소스 명칭 |
| `db` | string \| null | 아니오 | `null` | 원천 라벨 |
| `scope` | enum | 아니오 | `"all"` | `"all"` 또는 `"serving"` |

#### 응답 규격 (`MetaColumnResponse`)

```json
{
  "meta_version": "1.0",
  "column": {
    "column_name": "TAGSN",
    "column_name_kr": "태그일련번호",
    "data_type": "NUMBER(10)",
    "column_comment": "태그 일련번호",
    "description": "수질 계측 태그 마스터 일련번호 (PK/FK)",
    "constraints": ["PK", "FK"],
    "is_null": false,
    "nullability": "not_null",
    "column_is_active": "Y",
    "format_pattern": null,
    "unit": null,
    "facility_code": null,
    "system_code": null,
    "pk_ordinal": 1,
    "has_code": "Y",
    "has_code_status": "licensed",
    "code_lookup": {
      "ref_schema_name": "RWIS",
      "ref_table_name": "RDITAG_TB",
      "ref_column_name": "TAGSN",
      "via": "fk"
    },
    "term_mapping": {
      "standard_term": "태그일련번호",
      "physical_name": "TAGSN",
      "synonyms": ["태그번호", "TAG_NO"]
    },
    "value_examples": ["10001", "10002", "10003"],
    "provenance": {
      "label_ko": {
        "origin": "standard_term",
        "match_kind": "exact",
        "confidence": 1.0,
        "grade": "canonical"
      }
    }
  }
}
```

*컬럼이 존재하지 않는 경우 `404 Not Found` (`{"detail": "column not found"}`)가 반환됩니다.*

---

### 5.4 POST /meta/ref 및 별칭 POST /meta/fk (외래키 관계 조회)

지정된 테이블이 외부에 참조하는 모든 외래키(FK) 관계를 목록으로 조회합니다. `/meta/fk`는 동일한 동작을 수행하는 레거시 호환 엔드포인트입니다.

#### 요청 규격 (`TableKey`)

```json
{
  "schema_name": "RWIS",
  "table_name": "RDF01HH_TB",
  "db": "RWIS",
  "scope": "serving"
}
```

#### 응답 규격 (`MetaRefResponse`)

```json
{
  "meta_version": "1.0",
  "fk": [
    {
      "column_name": "TAGSN",
      "position": 1,
      "ref_schema_name": "RWIS",
      "ref_table_name": "RDITAG_TB",
      "ref_column_name": "TAGSN"
    }
  ]
}
```

- `column_name`: 외래키를 보유한 출발 컬럼.
- `position`: 복합키 내 순번 (단일 컬럼 조인은 항상 `1`).
- `ref_schema_name`: 참조 대상 부모 테이블의 스키마.
- `ref_table_name`: 참조 대상 부모 테이블명.
- `ref_column_name`: 참조 대상 부모 테이블의 컬럼명.

---

### 5.5 POST /meta/batch (배치 카탈로그 테이블 목록)

스냅샷에 포함된 전체 테이블의 기본 목록을 조회합니다. 대량 테이블 탐색을 위한 Keyset 커서 페이징을 지원합니다.

#### 요청 규격 (`BatchRequest`)

```json
{
  "batch_date": null,
  "scope": "serving",
  "limit": 100,
  "cursor": null
}
```

| 필드명 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `batch_date` | string \| null | 아니오 | `null` | 구버전 호환 파라미터. 스냅샷 특성상 필터되지 않고 `ignored_params`에 보고됨 |
| `scope` | enum | 아니오 | `"all"` | `"all"` 또는 `"serving"` |
| `limit` | int \| null | 아니오 | `null` | 한 페이지 최대 건수 (미지정 시 전량 조회) |
| `cursor` | string \| null | 아니오 | `null` | 이전 응답의 `next_cursor` |

#### 응답 규격 (`BatchResponse`)

```json
{
  "meta_version": "1.0",
  "items": [
    {
      "db": "RWIS",
      "schema_name": "RWIS",
      "table_name": "RDF01HH_TB",
      "table_name_kr": "시간 데이터",
      "table_comment": "시간 데이터",
      "description": "시간별 계측 팩트 테이블",
      "subject_area": "raw"
    },
    {
      "db": "RWIS",
      "schema_name": "RWIS",
      "table_name": "RDITAG_TB",
      "table_name_kr": "태그 마스터",
      "table_comment": "태그 기준정보",
      "description": "계측 태그 기준정보 테이블",
      "subject_area": "master"
    }
  ],
  "total": 2,
  "total_row_count": 150,
  "truncated": true,
  "cap": 100,
  "next_cursor": "ZXlKc2FYTj...",
  "ignored_params": []
}
```

- `total`: **현재 응답 배열(`items`)에 포함된 건수**.
- `total_row_count`: 저장소 내 전체 대상 테이블 건수.
- `truncated`: 페이징으로 인해 데이터가 다음 페이지에 남아있는지 여부.
- `next_cursor`: 다음 페이지 조회를 위한 Keyset 인코딩 문자열.
- `ignored_params`: 요청에 포함되었으나 처리되지 않은 파라미터 목록 (예: `["batch_date"]`).

---

## 6. 부가 및 진단 엔드포인트

### 6.1 POST /t2sql (결정론적 Text-to-SQL)

자연어 질문으로부터 LLM 호출 없이 완전히 결정론적인 읽기 전용 SQL을 생성합니다.

- **요청 모델 (`T2SqlRequest`)**: `query` (필수), `include_matched_columns`, `table_limit`, `auto_resolve_entities`, `source_instance_id`.
- **응답 모델 (`T2SqlResponse`)**:
  - `sql`: 생성된 최종 SQL 구문.
  - `sql_status`: `"generated"`, `"failed"`, `"validation_failed"`.
  - `sql_fingerprint`: 생성된 SQL의 정규화 해시 지문 (이후 `/query_execute`의 검증에 사용).
  - `time_anchor`: 상대기간(예: "최근 7일")을 벽시계로 해석했는지, 적재 최신시각(`latest_data_time`)으로 해석했는지에 대한 근거 정보.
  - `scan_plan`: 라이브 DB 인덱스를 참조하여 인덱스 구간 스캔을 유도했는지 여부 리포트.
  - `pipeline_stages`: SQL 생성 파이프라인의 각 단계별 소요 시간 및 상태.

### 6.2 GET /meta/coverage (메타데이터 슬롯별 채움률 리포트)

현재 활성 스냅샷에서 온톨로지 앵커, 리니지, 용어 매핑, 공인 근거(Canonical Provenance)가 실제로 몇 건 채워졌는지를 계측하여 반환합니다.
수치를 임의로 하드코딩하지 않고 실시간 카운트를 반환합니다.

### 6.3 POST /meta/table/graph (스냅샷 ↔ 라이브 그래프 드리프트 진단)

메타 스냅샷 투영 데이터와 라이브 Neo4j 지식 그래프 간의 차이(추가/삭제된 컬럼, 변경 속성)를 진단합니다.
라이브 조회를 수반하므로 결정론적이지 않으며(`deterministic: false`), 드리프트 발생 여부를 관측하는 데 사용됩니다.

### 6.4 폐기 경로 안내 (410 Gone)

- `POST /semantic_decision`: `410 Gone` 반환 (`/data_decision` 사용 안내).
- `POST /query/execute`: `410 Gone` 반환 (`/query_execute` 사용 안내).
- `POST /query_execute`의 `artifact_id` 파라미터 전달: `410 Gone` 반환 (`SEMANTIC_ARTIFACT_GONE`).

---

## 7. 일반적인 호출 흐름 (End-to-End 시나리오)

```
[0. 메타 동기화 및 헬스 체크]
GET /health
 └─> RWIS updated_at: "2026-09-15T10:56:51.378995+00:00"
      (로컬 캐시 최신 상태 확인 -> /meta 전량 재요청 생략)
                       │
                       ▼
[1. 사용자 질의: "화성정수장 최근 7일 탁도 평균"]
                       │
                       ▼
POST /data_decision 호출
┌─────────────────────────────────────────────────────────────┐
│ • 질문 형태소 분석 및 온톨로지 코어 판정                    │
│ • 태그 엔티티 해소 (화성정수장 탁도 -> TAGSN: [10001, 10002])│
│ • 후보 테이블 추천: RDF01HH_TB (시간 계측 Fact)            │
│ • 실행 컨텍스트 도출: source_instance_id = "RWIS"           │
└─────────────────────────────────────────────────────────────┘
                       │
                       ▼ (필요 시 세부 스펙 보강)
POST /meta/table 또는 POST /meta/column 호출
┌─────────────────────────────────────────────────────────────┐
│ • time_column ("LOG_TIME") 및 latest_data_time 확인         │
│ • TAGSN의 외래키 참조 관계 (RDITAG_TB) 검증                │
│ • 단위(NTU) 및 컬럼 데이터타입 확인                        │
└─────────────────────────────────────────────────────────────┘
                       │
                       ▼
SQL 생성 (POST /t2sql 또는 에이전트 생성)
┌─────────────────────────────────────────────────────────────┐
│ SELECT AVG(VAL) AS avg_turbidity                            │
│ FROM `RWIS`.`RWIS`.`RDF01HH_TB`                             │
│ WHERE TAGSN IN (10001, 10002)                               │
│   AND LOG_TIME >= '20260202000000'                          │
└─────────────────────────────────────────────────────────────┘
                       │
                       ▼
POST /query_execute 호출
┌─────────────────────────────────────────────────────────────┐
│ • 읽기 전용 가드 및 타임아웃(10s) 적용                      │
│ • RWIS 티베로 원천 엔진 쿼리 실행                          │
│ • 결과 행셋(2차원 배열) 반환                                │
└─────────────────────────────────────────────────────────────┘
```

본 명세서는 `stone-meta-api`의 모든 서비스 계약 정본을 담고 있으며, 상기 서술된 모든 요청/응답 모델과 제약 조건은 자동화된 회귀 시험 게이트(`backend/tests/test_stone_meta_api_contract.py`, `backend/tests/test_robo_parity_gate.py`)에 의해 바이트 단위로 검증됩니다.
