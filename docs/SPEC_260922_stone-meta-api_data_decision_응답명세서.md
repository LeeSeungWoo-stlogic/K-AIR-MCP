# stone-meta-api 종합 API 명세서 (data_decision · query_execute · meta)

| 항목 | 값 |
|---|---|
| 문서 상태 | 정본 (종합 전면 개정판) |
| 기준일 | 2026-09-22 |
| 이전 버전 | `SPEC_260922_stone-meta-api_data_decision_응답명세서.md` (data_decision 단독 명세) |
| 대상 서비스 | K-AIR-Stone `stone-meta-api` |
| 지원 경로 | `GET /health`, `POST /data_decision`, `POST /query_execute`, `POST /t2sql`<br>`POST /meta/catalog`, `POST /meta/table`, `POST /meta/column`, `POST /meta/ref`, `POST /meta/fk`, `POST /meta/batch`<br>진단: `GET /meta/coverage`, `POST /meta/table/graph`<br>폐기(410): `POST /semantic_decision`, `POST /query/execute` |
| 계약 정본 | `K-AIR-Stone/backend/services/stone_meta/contract.py` |
| 라우터 구현 | `K-AIR-Stone/backend/routers/stone_meta_api.py` |
| 메타 서비스 | `K-AIR-Stone/backend/services/stone_meta/meta_service.py` |
| 쿼리 실행기 | `K-AIR-Stone/backend/services/stone_meta/execute.py` |
| 계약 버전 | `meta_version: "1.0"` (응답 헤더 `X-Meta-Version: 1.0` 상시 동봉) |

---

## 1. 개요 및 아키텍처

`stone-meta-api`는 K-AIR 플랫폼에서 자연어 질의 분석, 메타데이터 서빙, 결정론적 SQL 생성 및 안전한 쿼리 실행을 전담하는 핵심 백엔드 서비스입니다.
기존 `robo-meta-api`의 9대 계약 인터페이스를 바이트 단위 호환성(Parity)을 유지하면서 계승하고, 다중 데이터소스 바인딩, 스냅샷 승인 거버넌스, 근거(Provenance) 추적, 파티션/인덱스 힌트 등의 엔터프라이즈 기능을 확장하여 제공합니다.

### 1.1 전체 엔드포인트 일람

| 분류 | HTTP 메서드 및 경로 | 설명 | 주요 입/출력 모델 |
|---|---|---|---|
| **의사결정** | `POST /data_decision` | 자연어 질문 기반 테이블/컬럼 후보 추천, 온톨로지 매핑, 엔티티 해소 | `DecisionRequest` → `DecisionResponse` |
| **쿼리실행** | `POST /query_execute` | 검증된 읽기 전용 SQL 실행 (가드, 타임아웃, 2단/3단 식별자 해석) | `QueryExecuteRequest` → `QueryExecuteResponse` |
| **메타서빙**<br>(핵심) | `POST /meta/catalog` | 서빙 테이블 목록 전량(컬럼·FK 포함) 또는 Keyset 페이징 조회 | `CatalogRequest` → `CatalogResponse` |
| | `POST /meta/table` | 단일 테이블의 상세 메타데이터 (컬럼, FK, 거버넌스, 리니지, 앵커) | `TableKey` → `MetaTableResponse` |
| | `POST /meta/column` | 단일 컬럼의 상세 메타데이터 (데이터타입, 제약, 코드사전, 용어매핑) | `ColumnRequest` → `MetaColumnResponse` |
| | `POST /meta/ref` | 테이블의 외래키(FK) 참조 관계 목록 조회 | `TableKey` → `MetaRefResponse` |
| | `POST /meta/fk` | `/meta/ref`의 레거시 호환 별칭 (동일 동작) | `TableKey` → `MetaRefResponse` |
| | `POST /meta/batch` | 배치 단위 카탈로그 테이블 목록 조회 (Keyset 페이징 지원) | `BatchRequest` → `BatchResponse` |
| **SQL생성** | `POST /t2sql` | 자연어 기반 결정론적 읽기 SQL 생성 (LLM 0회 호출 보장) | `T2SqlRequest` → `T2SqlResponse` |
| **진단/헬스** | `GET /health` | 메타데이터 저장소 헬스체크 및 활성 스냅샷 정보 반환 | `HealthResponse` |
| | `GET /meta/coverage` | 메타데이터 슬롯별 채움률 리포트 (온톨로지, 리니지, 근거 채움률) | `CoverageReport` |
| | `POST /meta/table/graph` | 스냅샷 대 라이브 Neo4j 그래프 드리프트 대조 리포트 | `TableKey` → `GraphDriftReport` |
| **폐기안내** | `POST /semantic_decision`<br>`POST /query/execute` | 구버전 호출 클라이언트를 위한 410 Gone 스텁 안내 경로 | 410 Gone 반환 |

### 1.2 호출 창구 및 네트워크 구성

| 창구 형태 | Base URL | 비고 |
|---|---|---|
| **단독 컨테이너 직접 접속** | `http://<host>:8096` | 내부 마이크로서비스 간 직접 호출 포트 |
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

## 2. POST /data_decision (메타 의사결정)

자연어 질의를 분석하여 가장 적합한 테이블 후보군(Top-K), 컬럼 매칭 정보, 온톨로지 앵커 및 검수된 사전 기반 엔티티 해소 결과를 종합하여 반환합니다.

### 2.1 요청 규격 (`DecisionRequest`)

| 필드명 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `query` | string (min 1) | **예** | — | 사용자의 자연어 검색 질의 (예: `"화성정수장 최근 일주일간 탁도 평균"`) |
| `include_matched_columns`| bool | 아니오 | `true` | `false` 지정 시 `candidates[].matched_columns`를 빈 배열로 반환 |
| `column_top_m` | int (1~50) \| null | 아니오 | `10` | 테이블별 벡터/어휘 매칭 컬럼 상한 |
| `table_limit` | int (1~50) \| null | 아니오 | `10` | 추천 테이블 후보 상한 (Top-K) |
| `auto_resolve_entities` | bool | 아니오 | `true` | 시설, 태그, 코드사전 기반 엔티티 자동 해소 수행 여부 |
| `source_instance_id` | string \| null | 아니오 | `null` | 특정 데이터소스로 탐색 범위 한정 (지정하지 않으면 전 원천 탐색) |

### 2.2 응답 규격 (`DecisionResponse`)

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

## 3. POST /query_execute (안전한 읽기 전용 쿼리 실행)

MindsDB 및 원천 데이터베이스를 경유하여 읽기 전용 쿼리를 안전하게 실행하고 결과를 표 형태로 반환합니다.

### 3.1 안전 가드 및 실행 제약

- **읽기 전용 가드**: `SELECT`, `WITH`, `EXPLAIN`(ANALYZE 제외), `SHOW` 문만 허용합니다. `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `GRANT`, 세션 변경 등 모든 변경/관리 구문은 `400 Bad Request`로 즉각 차단됩니다.
- **다중 구문 금지**: 세미콜론(`;`)으로 연결된 다중 쿼리 실행은 허용되지 않습니다.
- **실행 시간 제한**: `timeout_s`는 1~120초 범위이며, 기본값은 10초입니다.
- **반환 행수 제한**: `max_rows`는 1~100,000 범위로 요청 가능하나, 서버 절대 상한은 10,000행입니다 (기본 1,000행).
- **식별자 해석 규칙**:
  - 3단 표기: `` `SourceName`.`Schema`.`Table` `` (플랫폼 연결 소스명 권장)
  - 2단 표기: `` `Schema`.`Table` `` (`allowed_schemas` 또는 단일 소스 자동 바인딩)
  - MindsDB 내부 UUID 카탈로그는 노출되지 않고 플랫폼 소스 표시명으로 치환됩니다.

### 3.2 요청 규격 (`QueryExecuteRequest`)

| 필드명 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `sql` | string | **예** | — | 실행할 읽기 전용 SQL (예: ``SELECT * FROM `RWIS`.`RWIS`.`RDF01HH_TB` LIMIT 5``) |
| `execution_context` | `ExecutionContext` \| null | 아니오 | `null` | `/data_decision`에서 반환된 실행 컨텍스트. 미지정 시 SQL 구문의 식별자에서 자동 해석 |
| `timeout_s` | int (1~120) \| null | 아니오 | `10` | 쿼리 타임아웃 (초 단위) |
| `max_rows` | int (1~100000) \| null | 아니오 | `1000` | 최대 반환 행수 |
| `fingerprint` | string \| null | 아니오 | `null` | `/t2sql`에서 발급한 `sql_fingerprint`. 지정 시 SQL 위변조 검증 수행 |
| `artifact_id` | string \| null | **금지** | `null` | 폐기된 파라미터. 지정 시 `410 SEMANTIC_ARTIFACT_GONE` 오류 반환 |

### 3.3 응답 규격 (`QueryExecuteResponse`)

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

## 4. 메타데이터 핵심 엔드포인트군 (/meta/*)

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

### 4.1 POST /meta/catalog (서빙 카탈로그 목록 및 페이징)

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
  "source_instance_id": "kwater_source_rwis",
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
              "comment": "태그일련번호",
              "description": "태그 마스터 테이블의 기본키 참조 일련번호",
              "references": {
                "schema_name": "RWIS",
                "table_name": "RDITAG_TB",
                "column_name": "TAGSN",
                "constraint_name": "FK_RDF01HH_TAG",
                "position": 1
              },
              "referenced_by": null
            }
          ]
        }
      ]
    }
  ],
  "truncated": false,
  "next_cursor": null
}
```

---

### 4.2 POST /meta/table (단일 테이블 상세 메타데이터)

지정한 단일 테이블의 완전한 상세 스펙을 조회합니다. 거버넌스 승인 상태, 리니지(상류/하류 테이블), 5계층 온톨로지 앵커, 대표 시간 컬럼 및 컬럼 전체의 메타데이터를 일괄 반환합니다.

#### 요청 규격 (`TableKey`)

```json
{
  "schema_name": "RWIS",
  "table_name": "RDF01HH_TB",
  "source_name": "RWIS",
  "db": "RWIS",
  "scope": "serving"
}
```

#### 응답 규격 (`MetaTableResponse`)

```json
{
  "meta_version": "1.0",
  "table_info": {
    "db": "RWIS",
    "schema_name": "RWIS",
    "table_name": "RDF01HH_TB",
    "row_count": 15420000,
    "table_name_kr": "시간 데이터",
    "table_comment": "시간 데이터",
    "description": "시간별 탁도·유량 계측 팩트 테이블. TAGSN으로 태그 마스터와 조인.",
    "subject_area": "raw",
    "time_column": "LOG_TIME",
    "latest_data_time": "2026-02-09 24:00",
    "table_type": "Fact",
    "default_date_column": "LOG_TIME",
    "table_is_active": "Y",
    "pk_columns": ["TAGSN", "LOG_TIME"],
    "datasource": {
      "id": "kwater_source_rwis",
      "dialect": "tibero",
      "domain": "계측",
      "owner": "수자원운영처"
    },
    "lineage_brief": {
      "upstream": [{"schema_name": "RWIS", "table_name": "RDF01MI_TB"}],
      "downstream": [{"schema_name": "RWIS", "table_name": "RDF01DD_TB"}]
    },
    "ontology_anchors": [
      {"layer": "Measure", "name": "탁도", "relation": "MEASURES"},
      {"layer": "Process", "name": "정수처리공정", "relation": "PRODUCES"}
    ],
    "provenance": {
      "label_ko": {
        "origin": "standard_term",
        "match_kind": "exact",
        "confidence": 1.0,
        "evidence": "표준용어사전 매핑 일치",
        "grade": "canonical"
      }
    },
    "governance": {
      "review_status": "approved",
      "text_to_sql_is_valid": true,
      "activation": {
        "active": true,
        "snapshot_id": "snap_20260920_v1",
        "generation": 12
      }
    }
  },
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
        "synonyms": ["태그번호", "TAG_NO", "태그코드"]
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
    },
    {
      "column_name": "LOG_TIME",
      "column_name_kr": "로그시각",
      "data_type": "VARCHAR2(14)",
      "column_comment": "측정 일시",
      "description": "계측 관측 시각 (YYYYMMDDHHMISS 포맷)",
      "constraints": ["PK"],
      "is_null": false,
      "nullability": "not_null",
      "column_is_active": "Y",
      "format_pattern": "YYYYMMDDHH24MISS",
      "unit": null,
      "pk_ordinal": 2,
      "has_code": "N",
      "has_code_status": "none",
      "value_examples": ["20260209230000", "20260209240000"]
    }
  ],
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

---

### 4.3 POST /meta/column (단일 컬럼 상세 메타데이터)

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

---

### 4.4 POST /meta/ref 및 별칭 POST /meta/fk (외래키 관계 조회)

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

---

### 4.5 POST /meta/batch (배치 카탈로그 테이블 목록)

#### 요청 규격 (`BatchRequest`)

```json
{
  "batch_date": null,
  "scope": "serving",
  "limit": 100,
  "cursor": null
}
```

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
    }
  ],
  "total": 1,
  "total_row_count": 150,
  "truncated": true,
  "cap": 100,
  "next_cursor": "ZXlKc2FYTj...",
  "ignored_params": []
}
```

---

## 5. 부가 및 진단 엔드포인트

- `POST /t2sql`: 자연어 → 결정론적 읽기 SQL 생성 (`sql_fingerprint`, `time_anchor`, `scan_plan`).
- `GET /health`: 저장소 헬스체크 및 `X-Meta-Version: 1.0` 헤더 반환.
- `GET /meta/coverage`: 메타데이터 슬롯별 실시간 채움률 리포트.
- `POST /meta/table/graph`: 스냅샷 ↔ 라이브 Neo4j 지식 그래프 드리프트 대조 리포트.
- 폐기 경로 안내: `POST /semantic_decision`, `POST /query/execute`, `QueryExecuteRequest.artifact_id` (410 Gone).
