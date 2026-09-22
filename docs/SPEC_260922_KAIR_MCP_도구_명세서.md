# Stone-meta-mcp 도구 명세서 (구 KAIR-MCP)

**작성일:** 2026-09-22  
**대상 서비스 / 모듈:** `Stone-meta-mcp` (`c:\Users\LSW\Documents\GitHub\K-AIR-Stone\stone-meta-mcp` 및 `c:\Users\LSW\Documents\GitHub\K-AIR-MCP`)  
**서버 명칭:** `stone-meta-mcp` (구 `kair-mcp`)  
**전송 방식:** Streamable HTTP (`/mcp`, `X-Api-Key` 또는 `Authorization: Bearer <KEY>`) 및 stdio 지원  
**연계 백엔드:** `stone-meta-api` (버전 1.0, 포트 `:8096` / `:8111`)  
**문서 위치:** `docs/SPEC_260922_KAIR_MCP_도구_명세서.md`  

---

## 1. 개요 및 핵심 아키텍처

**Stone-meta-mcp**는 LLM 에이전트가 데이터허브(K-water)의 승인된 원천 데이터 및 메타데이터를 안전하고 정합성 있게 탐색·조회·결합할 수 있도록 인터페이스를 제공하는 전용 MCP(Model Context Protocol) 서버입니다.  
`stone-meta-api`와 연계하여 완전 결정론적 메타데이터 서빙, MindsDB 경유 안전 조회 및 원천 DB(PostgreSQL/Tibero) 직조회를 지원합니다.

```
┌─────────────────────────────────────────────────────────────┐
│                    LLM Agent (Client)                       │
└──────────────────────────────┬──────────────────────────────┘
                               │ Streamable HTTP (/mcp) or stdio
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                      Stone-meta-mcp                         │
│  ┌─────────────────────────┐   ┌─────────────────────────┐  │
│  │     메타데이터 탐색     │   │      인메모리 결합      │  │
│  │   (Catalog / Table /    │   │      (join_tables       │  │
│  │     Column / Ref)       │   │   WHERE IN 2단계 주입)  │  │
│  └────────────┬────────────┘   └────────────┬────────────┘  │
└───────────────┼─────────────────────────────┼───────────────┘
                │                             │
        ┌───────┴───────────────┐     ┌───────┴───────────────┐
        ▼                       ▼     ▼                       ▼
┌────────────────┐     ┌──────────────────────────────────────┐
│ stone-meta-api │     │              원천 실행기             │
│ (포트 :8096)   │     │  - MindsDB (/query_execute)          │
│ • /meta/catalog│     │  - PostgreSQL 직조회 (asyncpg)       │
│ • /meta/table  │     │  - Tibero 7 직조회 (JDBC LIMIT)      │
│ • /meta/ref    │     └──────────────────────────────────────┘
└────────────────┘
```

### 핵심 운영 정책
1. **임의 SQL 미지원 (보안성 확보)**: 사용자가 작성한 임의 SQL 문자열을 직접 실행하지 않으며, 정형화된 필터/정렬/집계 파라미터만 파싱하여 조립 실행합니다.
2. **읽기 전용 가드**: INSERT, UPDATE, DELETE, DDL, GRANT, Dump 등의 쓰기/변경 작업을 원천 차단합니다.
3. **카탈로그 기반 인가**: `stone-meta-api POST /meta/catalog`에 등록되고 승인된 테이블만 조회가 허용됩니다.
4. **실행 경로 다원화**:
   - **MindsDB 경유 (`/query_execute`)**: 기본 조회 창구로 에이전트에 DB 비밀번호가 필요 없습니다.
   - **원천 DB 직조회 (`asyncpg` / `Tibero JDBC`)**: 고속/대용량 조회가 필요할 때 `set_credentials`를 통해 세션 메모리에 설정된 자격증명을 사용합니다.
5. **어플리케이션 레벨 결합 (`join_tables`)**: 이종 DB 간 또는 대규모 결합 시 DB 엔진 부하를 방지하기 위해 1단계 검색 키를 2단계 `WHERE IN (...)` 절로 자동 주입하여 인메모리 결합합니다.
6. **멀티턴 정제 유도 (`TOO_MANY_CANDIDATES`)**: 1단계 검색 키가 안전 상한(`max_in_keys`, 기본 100건)을 초과하면 조회를 중단하고 에이전트가 범위를 좁히도록 되묻게 유도합니다.
7. **상한치 완화**: 기본 `MCP_ROW_LIMIT`이 200에서 **1,000행**으로 상향되어 태그 목록(`tagsn`) 등 대량의 조건 키 추출을 원활히 지원합니다.

---

## 2. 등록 도구(Tools) 일람 (총 14개)

| 분류 | 도구명 (Tool Name) | 연계 엔드포인트 / 경로 | 인증(PW) 필요 | 주요 기능 및 반환 정보 |
|:---|:---|:---|:---:|:---|
| **메타 탐색** | `list_sources` | stone-meta + nk-backend | X | 카탈로그 소스·스키마 및 DB 엔진 목록 |
| | `list_tables` | `stone-meta-api POST /meta/catalog` | X | 허용된 테이블 물리명·한글 논리명·설명·업무영역 목록 |
| | `describe_table` | `stone-meta-api POST /meta/table` | X | 테이블 상세(시간컬럼, 최신시각, 리니지, 앵커, 거버넌스, 컬럼별 코드/용어/근거) |
| | `list_join_hints` | `stone-meta-api POST /meta/ref` | X | 해당 테이블의 정합 외래키(FK) 참조 관계 목록 |
| | `get_distinct_values` | `stone-meta-api POST /query_execute` | X | 특정 컬럼의 고유값 목록(DISTINCT) 조회 (최대 1,000건) |
| **행 조회** | `query_table` | MindsDB (`/query_execute`) | X | 단일 테이블 필터/정렬/컬럼 선택 SELECT 조회 |
| | `query_table_pg` | PostgreSQL 원천 직조회 (`asyncpg`) | **필요** | 원천 PG 단일 테이블 직조회 (고속 독립 실행) |
| | `query_table_tibero` | Tibero 원천 직조회 (JDBC) | **필요** | 원천 Tibero 단일 테이블 직조회 (`LIMIT N` 지원) |
| **데이터 집계** | `aggregate_table` | MindsDB (`/query_execute`) | X | 단일 테이블 집계 함수(`count`, `sum`, `avg`, `max`, `min`) 및 Group By |
| | `aggregate_table_pg` | PostgreSQL 원천 직조회 | **필요** | 원천 PG 테이블 집계 함수 및 Group By |
| | `aggregate_table_tibero` | Tibero 원천 직조회 | **필요** | 원천 Tibero 테이블 집계 함수 및 Group By |
| **테이블 결합** | `join_tables` | MCP 프로세스 인메모리 | 조건부 | 1단계 키 추출 → 2단계 WHERE IN 주입 후 인메모리 결합 |
| **인증 관리** | `set_credentials` | MCP 인메모리 세션 | - | 원천 직조회용 소스별 DB 계정(ID/PW) 등록 (API Key별 범위 격리) |
| | `clear_credentials` | MCP 인메모리 세션 | - | 등록된 원천 DB 계정 정보 삭제 (개별 또는 전체) |

---

## 3. 공통 규격 및 파라미터

### 3.1 Filters 규격
배열 형태로 전달하며, 각 항목은 `{ "column": string, "op": string, "value": any }` 형태입니다.
- **지원 연산자 (`op`)**:
  - `eq` (`=`): 동등 비교
  - `ne` (`<>`): 불일치 비교
  - `gt` (`>`), `gte` (`>=`): 초과 / 이상
  - `lt` (`<`), `lte` (`<=`): 미만 / 이하
  - `like` (`LIKE`): 와일드카드 문자열 검색 (예: `%탁도%`)
  - `in` (`IN`): 값 목록 포함 (`value`는 비어있지 않은 배열 필수)
  - `is_null` (`IS NULL`): NULL 여부 확인 (`value` 생략)
  - `is_not_null` (`IS NOT NULL`): NOT NULL 여부 확인 (`value` 생략)

### 3.2 Order By 규격
배열 형태로 전달하며, `{ "column": string, "dir": "asc" | "desc" }` 형태입니다. (`direction` 키도 허용)

### 3.3 Limit 및 상한치 정책
- **기본값**: 50행 (파라미터 미지정 시 기본 50행으로 반환)
- **서버 상한값**: `MCP_ROW_LIMIT` 환경 변수 (기본값 **10,000행**) 이내로 자동 보정(clamp)됩니다.
- **컨테이너 옵션화**: 로컬 LLM 및 대용량 시계열 계측 데이터 처리를 위해, 컨테이너 구축 시 환경변수(`MCP_ROW_LIMIT`)를 통해 허용 상한을 10,000건 이상으로 자유롭게 확장할 수 있습니다.
- 대량의 시계열 행 데이터나 태그 일련번호(`tagsn`) 추출이 필요한 경우 도구 호출 시 `limit: 10000`과 같이 필요한 행수를 명시하여 요청할 수 있습니다.

---

## 4. 도구별 상세 명세

### 4.1 메타데이터 탐색 도구

#### (1) `list_sources`
- **설명**: 카탈로그에 등록된 소스 및 스키마, DB 엔진 목록을 조회합니다. 보안을 위해 내부 IP 및 접속 비밀번호는 응답에서 제외됩니다.
- **파라미터**: 없음
- **응답 예시**:
  ```json
  {
    "total": 2,
    "items": [
      {
        "source_name": "RWIS",
        "engine": "tibero",
        "schema_name": "RWIS",
        "table_count": 48,
        "enabled": true,
        "credentials_set": false
      },
      {
        "source_name": "rwis_pg",
        "engine": "postgres",
        "schema_name": "public",
        "table_count": 12,
        "enabled": true,
        "credentials_set": false
      }
    ]
  }
  ```

#### (2) `list_tables`
- **설명**: `stone-meta-api POST /meta/catalog`를 참조하여 승인된 테이블 목록을 반환합니다. 물리 식별자 외에 한글 논리명, 테이블 설명, 업무 영역(`subject_area`)을 제공합니다.
- **파라미터**:
  - `schema_name` *(선택, string)*: 특정 스키마명으로 필터링
- **응답 예시**:
  ```json
  {
    "total": 2,
    "items": [
      {
        "source_name": "RWIS",
        "schema_name": "RWIS",
        "table_name": "RDF01HH_TB",
        "engine": "tibero",
        "table_logical_name": "시간 데이터",
        "description": "시간별 계측 팩트 테이블"
      },
      {
        "source_name": "RWIS",
        "schema_name": "RWIS",
        "table_name": "RDITAG_TB",
        "engine": "tibero",
        "table_logical_name": "태그 마스터",
        "description": "계측 태그 기준정보 테이블"
      }
    ]
  }
  ```

#### (3) `describe_table` (★핵심 메타 상세★)
- **설명**: `stone-meta-api POST /meta/table`을 호출하여 테이블의 완전한 상세 스펙을 조회합니다.
  - **테이블 정보**: 대표시간컬럼(`time_column`), 적재최신시각(`latest_data_time`), 상·하류 리니지(`lineage_brief`), 5계층 온톨로지 앵커(`ontology_anchors`), 거버넌스 승인 상태(`governance`).
  - **컬럼 정보**: 물리/논리명, 데이터타입, PK/FK 제약조건, 코드사전 매핑(`code_lookup`), 표준용어(`term_mapping`), 값 예시(`value_examples`), 근거 4요소(`provenance`), 3값 `nullability`('nullable'|'not_null'|'unknown'), 코드컬럼 평가상태(`has_code_status`).
  - **외래키 관계**: 외래키 참조 관계 리스트.
- **파라미터**:
  - `source_name` *(필수, string)*: 소스 이름
  - `schema_name` *(필수, string)*: 스키마 이름
  - `table_name` *(필수, string)*: 테이블 이름
- **응답 예시**:
  ```json
  {
    "source_name": "RWIS",
    "schema_name": "RWIS",
    "table_name": "RDF01HH_TB",
    "engine": "tibero",
    "logical_name": "시간 데이터",
    "description": "시간별 탁도·유량 계측 팩트 테이블. TAGSN으로 태그 마스터와 조인.",
    "time_column": "LOG_TIME",
    "latest_data_time": "2026-02-09 24:00",
    "table_type": "Fact",
    "lineage_brief": {
      "upstream": [{"schema_name": "RWIS", "table_name": "RDF01MI_TB"}],
      "downstream": [{"schema_name": "RWIS", "table_name": "RDF01DD_TB"}]
    },
    "ontology_anchors": [
      {"layer": "Measure", "name": "탁도", "relation": "MEASURES"}
    ],
    "governance": {
      "review_status": "approved",
      "text_to_sql_is_valid": true,
      "active": true
    },
    "columns": [
      {
        "column_name": "TAGSN",
        "data_type": "NUMBER(10)",
        "nullable": false,
        "nullability": "not_null",
        "primary_key": true,
        "logical_name": "태그일련번호",
        "comment": "태그 일련번호",
        "description": "수질 계측 태그 마스터 일련번호 (PK/FK)",
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
          "origin": "standard_term",
          "match_kind": "exact",
          "confidence": 1.0,
          "grade": "canonical"
        }
      },
      {
        "column_name": "LOG_TIME",
        "data_type": "VARCHAR2(14)",
        "nullable": false,
        "nullability": "not_null",
        "primary_key": true,
        "logical_name": "로그시각",
        "comment": "측정 일시",
        "description": "계측 관측 시각 (YYYYMMDDHHMISS)",
        "has_code": "N",
        "has_code_status": "none"
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

#### (4) `list_join_hints`
- **설명**: `stone-meta-api POST /meta/ref`를 호출하여 특정 테이블의 정합 외래키(FK) 참조 관계 목록을 반환합니다.
- **파라미터**: `source_name`, `schema_name`, `table_name` *(모두 필수, string)*
- **응답 예시**:
  ```json
  {
    "total": 1,
    "items": [
      {
        "from": { "source_name": "RWIS", "schema_name": "RWIS", "table_name": "RDF01HH_TB", "column_name": "TAGSN" },
        "to": { "source_name": "RWIS", "schema_name": "RWIS", "table_name": "RDITAG_TB", "column_name": "TAGSN" },
        "position": 1,
        "via": "meta-ref"
      }
    ]
  }
  ```

#### (5) `get_distinct_values`
- **설명**: 특정 컬럼의 고유값 목록(DISTINCT)을 MindsDB를 통해 안전하게 조회합니다.
- **파라미터**: `source_name`, `schema_name`, `table_name`, `column_name` *(필수)*, `limit` *(선택, 기본 50, 최대 1000)*

---

### 4.2 테이블 행 조회 도구

#### (1) `query_table`
- **설명**: 조립된 SELECT 문을 MindsDB(`stone-meta-api POST /query_execute`)를 통해 실행합니다. 별도의 DB 계정 없이 기본 구동됩니다.
- **파라미터**:
  - `source_name`, `schema_name`, `table_name` *(필수, string)*
  - `columns` *(선택, list[string])*: 조회할 컬럼 (생략 시 전체)
  - `filters` *(선택, list[dict])*: 필터 조건 배열
  - `order_by` *(선택, list[dict])*: 정렬 조건 배열
  - `limit` *(선택, int, 기본값 50, 최대 1000)*: 조회 제한 행수
- **응답 내 `via`**: `"mindsdb-query_execute"`

#### (2) `query_table_pg`
- **설명**: PostgreSQL 원천 DB에 직접 비동기 쿼리를 실행합니다 (`asyncpg`). 사전에 `set_credentials`가 필요합니다.
- **파라미터**: `query_table`과 동일
- **응답 내 `via`**: `"postgres-direct"`

#### (3) `query_table_tibero`
- **설명**: Tibero 7 Zeta 원천 DB에 JDBC를 통해 직접 쿼리를 실행합니다 (`LIMIT N` 지원). 사전에 `set_credentials`가 필요합니다.
- **파라미터**: `query_table`과 동일
- **응답 내 `via`**: `"tibero-direct"`

---

### 4.3 테이블 데이터 집계 도구

#### (1) `aggregate_table`
- **설명**: 집계 함수(`count`, `sum`, `avg`, `max`, `min`) 및 그룹화(Group By) 쿼리를 MindsDB를 통해 실행합니다.
- **파라미터**:
  - `source_name`, `schema_name`, `table_name` *(필수, string)*
  - `func` *(필수, string)*: `count` | `sum` | `avg` | `max` | `min`
  - `column` *(선택, string)*: 집계 대상 컬럼 (`count` 시 생략 가능)
  - `group_by` *(선택, list[string])*: 그룹화 컬럼 목록
  - `filters` *(선택, list[dict])*: 사전 필터
  - `limit` *(선택, int, 기본값 50)*: 그룹 결과 행 제한

#### (2) `aggregate_table_pg` / `aggregate_table_tibero`
- **설명**: 원천 PostgreSQL 또는 Tibero에 집계 쿼리를 직접 실행합니다 (`set_credentials` 필요).

---

### 4.4 테이블 결합(Join) 도구

#### `join_tables` (★2단계 WHERE IN 결합 및 상한 연동★)
- **동작 원리**:
  1. 1단계: 마스터/코드(left) 테이블의 조건을 기반으로 키 목록을 조회합니다.
  2. 키 추출 및 상한 검사: 추출된 고유 키 개수가 `max_in_keys`(기본 100건)를 초과하면 무리하게 2단계 조회를 실행하지 않고, `TOO_MANY_CANDIDATES` 상태와 함께 안내 메시지를 반환하여 사용자에게 조건을 좁히도록 유도합니다.
  3. 2단계: 안전 상한 이내인 경우 추출된 키들을 팩트(right) 테이블의 `WHERE right_on IN (...)` 절로 자동 주입하여 조회합니다.
  4. 인메모리 결합: 두 결과 셋을 MCP 메모리 상에서 결합하여 반환합니다.
- **상한 연동 개선사항 (방안 1 & 방안 3 반영)**:
  - **1단계 `left_limit` 자동 연동**: `left_limit`이 생략되었거나 `max_in_keys`보다 작으면 최소 `max_in_keys` 이상(`max(50, max_in_keys)`)으로 자동 확장하여 키 후보를 충분히 확보합니다.
  - **2단계 `right_limit` 자동 할당**: `right_limit` 미지정 시 추출된 키 수와 `row_limit`을 고려하여 행 상한을 자동 계산합니다 (`max(50, min(키수 * 10, row_limit))`).
  - **도구 인자로 직접 상향 가능**: 에이전트가 `max_in_keys: 300`과 같이 인자를 넘겨 안전 상한을 직접 확장할 수 있습니다.
- **파라미터**:
  - `left_source_name`, `left_schema_name`, `left_table_name` *(필수, string)*
  - `left_on` *(필수, string | list[string])*: 왼쪽 테이블 조인 키 컬럼
  - `right_source_name`, `right_schema_name`, `right_table_name` *(필수, string)*
  - `right_on` *(필수, string | list[string])*: 오른쪽 테이블 조인 키 컬럼
  - `left_via`, `right_via` *(선택, string, 기본값 `"mindsdb"`)*: `"mindsdb"` | `"pg"` | `"tibero"`
  - `left_columns`, `right_columns` *(선택, list[string])*: 출력 컬럼
  - `left_filters`, `right_filters` *(선택, list[dict])*: 각 면 사전 필터
  - `left_limit` *(선택, int, 기본값 None)*: 1단계 조회 상한. 생략 시 `max_in_keys`와 자동 연동
  - `right_limit` *(선택, int, 기본값 None)*: 2단계 조회 상한. 생략 시 자동 할당
  - `how` *(선택, string, 기본값 `"inner"`)*: `"inner"` | `"left"`
  - `max_in_keys` *(선택, int, 기본값 100)*: 2단계 WHERE IN 주입 최대 키 수 한도
- **응답 예시 (정상 결합 시)**:
  ```json
  {
    "via": "mcp-assemble",
    "how": "inner",
    "status": "SUCCESS",
    "left": { "source_name": "RWIS", "table_name": "RDITAG_TB", "on": ["TAGSN"], "fetched": 2 },
    "right": { "source_name": "RWIS", "table_name": "RDF01HH_TB", "on": ["TAGSN"], "fetched": 10 },
    "row_count": 10,
    "items": [
      {
        "left": { "TAGSN": 10001, "TAGNM": "화성정수장 침전지 탁도" },
        "right": { "TAGSN": 10001, "LOG_TIME": "20260209230000", "VAL": 0.045 }
      }
    ]
  }
  ```
- **응답 예시 (후보 과다로 되묻기 유도 시)**:
  ```json
  {
    "via": "mcp-assemble",
    "how": "inner",
    "status": "TOO_MANY_CANDIDATES",
    "candidate_count": 142,
    "threshold": 100,
    "sample_candidates": [10001, 10002, 10003, 10004, 10005],
    "message": "1단계 마스터 검색 결과 조인 키 'TAGSN'의 대상이 142건으로 안전 상한(100건)을 초과했습니다. WHERE IN 절 과부하를 방지하기 위해 2단계 조회를 중단합니다. 사용자에게 시설명, 계측 항목 등 조건을 구체화하여 범위를 좁히도록 되물어보세요.",
    "left": { "source_name": "RWIS", "table_name": "RDITAG_TB", "on": ["TAGSN"], "fetched": 142 },
    "right": null,
    "row_count": 0,
    "items": []
  }
  ```

---

### 4.5 자격 증명(인증) 관리 도구

#### (1) `set_credentials`
- **설명**: 원천 DB 직조회(`*_pg`, `*_tibero`)에 필요한 로그인 정보(ID/PW)를 프로세스 메모리에 저장합니다. API Key별로 범위가 격리되며 응답에 비밀번호는 제외됩니다.
- **파라미터**: `source_name` *(필수)*, `user` *(필수)*, `password` *(필수)*

#### (2) `clear_credentials`
- **설명**: 메모리에 저장된 자격 증명을 삭제합니다.
- **파라미터**: `source_name` *(선택, 생략 시 해당 호출자 세션의 모든 계정 삭제)*

---

## 5. 관리 및 진단 엔드포인트

- **생존 확인 (Liveness)**: `GET /health`
  - 의존 서비스 호출 없이 즉시 생존 응답 (`{"status": "ok", "server": "stone-meta-mcp", "transport": "streamable-http", "ready": "/health/ready"}`)
- **준비 확인 (Readiness)**: `GET /health/ready`
  - `stone-meta-api GET /health` 통신 상태 점검 (필수 통신 실패 시 503 반환).
- **전송 계층 및 인증**:
  - 엔드포인트: `/mcp` (포트 `:8111` 또는 프록시 `:8096/mcp`, `:8097/mcp`)
  - 인증 헤더: `X-Api-Key: <MCP_API_KEYS>` 또는 `Authorization: Bearer <MCP_API_KEYS>`
