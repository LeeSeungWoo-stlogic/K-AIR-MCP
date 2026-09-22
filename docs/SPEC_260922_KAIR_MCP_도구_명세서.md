# K-AIR MCP 도구 명세서 (kair-mcp-analyze)

**작성일:** 2026-09-22  
**대상 저장소:** `K-AIR-MCP` (`c:\Users\LSW\Documents\GitHub\K-AIR-MCP`)  
**서버 명칭:** `kair-mcp-analyze`  
**전송 방식:** Streamable HTTP (`/mcp`, `X-Api-Key`) 및 stdio 지원  
**문서 위치:** `K-water_docs/40_연동_운영/mcp_조회셋/SPEC_260922_KAIR_MCP_도구_명세서.md`

---

## 1. 개요 및 기본 원칙

K-AIR MCP는 LLM 에이전트가 데이터허브(K-water)의 승인된 데이터를 안전하게 조회할 수 있도록 인터페이스를 제공하는 MCP(Model Context Protocol) 서버입니다.

### 핵심 정책
1. **임의 SQL 미지원 (안전성 확보)**: 사용자가 작성한 임의 SQL 문자열을 직접 실행하지 않으며, 조립형 SELECT/집계 파라미터만 허용합니다.
2. **읽기 전용 (DML/DDL 차단)**: INSERT, UPDATE, DELETE, DDL, Dump 등의 쓰기/변경 작업을 원천 차단합니다.
3. **카탈로그 기반 인가**: `stone-meta-api POST /meta/catalog`에 등록되고 허용된 PostgreSQL 및 Tibero 테이블만 조회가 가능합니다.
4. **실행 경로의 이원화**:
   - **MindsDB 경유 (`/query_execute`)**: 기본 조회 창구로, 에이전트에 DB 비밀번호가 필요 없습니다.
   - **원천 DB 직조회 (`asyncpg` / `Tibero JDBC`)**: 빠른 응답 또는 특정 원천 조회가 필요할 때 사용하며, `set_credentials`를 통해 세션 메모리에 설정된 인증 정보를 사용합니다.
5. **어플리케이션 레벨 JOIN (`join_tables`)**: 이종 DB 간 또는 대규모 결합 시 DB 엔진에 부하를 주지 않고, 각각의 데이터를 조회한 후 MCP 프로세스 메모리 상에서 결합합니다.

---

## 2. 등록된 도구(Tools) 총괄 요약 (14개)

| 분류 | 도구명 (Tool Name) | 실행 경로 / 대상 | 인증(PW) 필요 | 주요 기능 |
|:---|:---|:---|:---:|:---|
| **메타 탐색** | `list_sources` | stone-meta + nk-backend | X | 카탈로그 소스·스키마 및 접속 좌표(Host/Port/DB) 목록 |
| | `list_tables` | stone-meta `/meta/catalog` | X | 허용된 테이블 물리명·한글 논리명·설명 목록 조회 |
| | `describe_table` | stone-meta `/meta/table` | X | 특정 테이블의 컬럼 타입, PK, 논리명, 코멘트, FK 조회 |
| | `list_join_hints` | stone-meta `/meta/ref` | X | 특정 테이블의 외래키(FK) 참조 관계 힌트 목록 조회 |
| | `get_distinct_values` | stone-meta `/query_execute` | X | 특정 컬럼의 고유값(DISTINCT) 목록 조회 |
| **행 조회** | `query_table` | MindsDB (`/query_execute`) | X | 단일 테이블 필터/정렬/컬럼 선택 SELECT 조회 |
| | `query_table_pg` | PostgreSQL 원천 직조회 (asyncpg) | **필요** | 원천 PG 단일 테이블 직조회 (고속/독립 실행) |
| | `query_table_tibero` | Tibero 원천 직조회 (JDBC) | **필요** | 원천 Tibero 단일 테이블 직조회 (`tibero-jdbc.jar`) |
| **데이터 집계** | `aggregate_table` | MindsDB (`/query_execute`) | X | 단일 테이블 집계 함수(count, sum, avg, max, min) 및 Group By |
| | `aggregate_table_pg` | PostgreSQL 원천 직조회 | **필요** | 원천 PG 테이블 집계 함수 및 Group By |
| | `aggregate_table_tibero` | Tibero 원천 직조회 | **필요** | 원천 Tibero 테이블 집계 함수 및 Group By |
| **테이블 결합** | `join_tables` | MCP 프로세스 인메모리 | 조건부 | 두 테이블을 각각 조회 후 MCP 메모리에서 Inner/Left 조인 |
| **인증 관리** | `set_credentials` | MCP 인메모리 세션 | - | 원천 직조회용 소스별 DB 계정(ID/PW) 등록 (결과엔 미노출) |
| | `clear_credentials` | MCP 인메모리 세션 | - | 등록된 원천 DB 계정 정보 삭제 (개별 또는 전체) |

---

## 3. 공통 규격 (Filters, Order, Limit)

`query_table*`, `aggregate_table*`, `join_tables`에서 공통으로 사용되는 조건문 규격입니다.

### 3.1 Filters 규격
배열 형태로 전달하며, 각 항목은 `{ "column": string, "op": string, "value": any }` 형태의 객체입니다.
- **지원 연산자 (`op`)**:
  - `eq` (`=`): 동등 비교
  - `ne` (`<>`): 불일치 비교
  - `gt` (`>`), `gte` (`>=`): 초과 / 이상
  - `lt` (`<`), `lte` (`<=`): 미만 / 이하
  - `like` (`LIKE`): 와일드카드 문자열 검색 (예: `%검색어%`)
  - `in` (`IN`): 값 목록 포함 (`value`는 비어있지 않은 배열 필수)
  - `is_null` (`IS NULL`): NULL 여부 확인 (`value` 불필요)
  - `is_not_null` (`IS NOT NULL`): NOT NULL 여부 확인 (`value` 불필요)

### 3.2 Order By 규격
배열 형태로 전달하며, `{ "column": string, "dir": "asc" | "desc" }` 형태입니다. (키 이름은 `dir` 또는 `direction` 허용)

### 3.3 Limit 제한
- 기본값: 50행
- 상한값: 환경 변수 `MCP_ROW_LIMIT` (기본값 200행) 이내로 자동 보정(clamp)됩니다.

---

## 4. 도구별 상세 명세

### 4.1 메타데이터 탐색 도구

#### (1) `list_sources`
- **설명**: 카탈로그에 등록된 소스 및 스키마, 그리고 `nk-backend`의 data-fabric 접속 좌표(Host, Port, DB, 활성 여부 등)를 종합하여 반환합니다.
- **파라미터**: 없음
- **응답 필드 예시**:
  ```json
  {
    "total": 3,
    "items": [
      {
        "source_name": "rwis_pg",
        "engine": "postgres",
        "schema_name": "public",
        "table_count": 48,
        "host": "10.0.0.1",
        "port": 5432,
        "database": "rwis",
        "username": "kair_user",
        "enabled": true,
        "credentials_set": false
      }
    ]
  }
  ```

#### (2) `list_tables`
- **설명**: 카탈로그의 PostgreSQL 및 Tibero 테이블 이름 목록을 반환합니다. 물리적 식별 3키(`source_name`, `schema_name`, `table_name`) 외에 한글 논리명과 테이블 설명을 제공합니다.
- **파라미터**:
  - `schema_name` *(선택, string)*: 특정 스키마명으로 필터링
- **응답 필드 예시**:
  ```json
  {
    "total": 1,
    "items": [
      {
        "source_name": "rwis_pg",
        "schema_name": "public",
        "table_name": "tb_water_quality",
        "engine": "postgres",
        "table_logical_name": "수질 측정 데이터",
        "description": "실시간 정수장 수질 측정 테이블"
      }
    ]
  }
  ```

#### (3) `describe_table`
- **설명**: 특정 테이블의 상세 메타데이터(컬럼 타입, PK 여부, Nullable, 한글 논리명, 코멘트, 외래키 참조 관계)를 조회합니다 (`POST /meta/table`).
- **파라미터**:
  - `source_name` *(필수, string)*: 소스 이름
  - `schema_name` *(필수, string)*: 스키마 이름
  - `table_name` *(필수, string)*: 테이블 이름
- **응답 필드 예시**:
  ```json
  {
    "source_name": "rwis_pg",
    "schema_name": "public",
    "table_name": "tb_water_quality",
    "engine": "postgres",
    "logical_name": "수질 측정 데이터",
    "description": "실시간 정수장 수질 측정 테이블",
    "columns": [
      {
        "column_name": "site_cd",
        "data_type": "varchar(10)",
        "nullable": false,
        "primary_key": true,
        "logical_name": "사업소 코드",
        "comment": "정수장 고유 식별 코드",
        "references": null,
        "referenced_by": null
      }
    ]
  }
  ```

#### (4) `list_join_hints`
- **설명**: 카탈로그 메타데이터에 명시된 외래키(`POST /meta/ref`) 참조 관계 목록을 반환합니다. (추론 기반 infer-FK는 생성하지 않음)
- **파라미터**:
  - `source_name` *(필수, string)*
  - `schema_name` *(필수, string)*
  - `table_name` *(필수, string)*
- **응답 필드 예시**:
  ```json
  {
    "total": 1,
    "items": [
      {
        "from": { "source_name": "rwis_pg", "schema_name": "public", "table_name": "tb_measure", "column_name": "site_cd" },
        "to": { "source_name": "rwis_pg", "schema_name": "public", "table_name": "tb_site", "column_name": "site_cd" },
        "position": 1,
        "via": "meta-ref"
      }
    ]
  }
  ```

#### (5) `get_distinct_values`
- **설명**: 특정 컬럼의 고유값 목록(DISTINCT)을 MindsDB를 통해 조회합니다.
- **파라미터**:
  - `source_name` *(필수, string)*
  - `schema_name` *(필수, string)*
  - `table_name` *(필수, string)*
  - `column_name` *(필수, string)*: 대상 컬럼명
  - `limit` *(선택, int, 기본값 50)*: 조회 상한선

---

### 4.2 테이블 행 조회 도구

#### (1) `query_table`
- **설명**: 단일 테이블에 대해 조립된 SELECT 문을 MindsDB(`stone-meta-api POST /query_execute`)를 통해 실행합니다. 별도의 DB 계정이 필요 없습니다.
- **파라미터**:
  - `source_name` *(필수, string)*
  - `schema_name` *(필수, string)*
  - `table_name` *(필수, string)*
  - `columns` *(선택, list[string])*: 조회할 컬럼 배열 (생략 시 전체)
  - `filters` *(선택, list[dict])*: 필터 조건 배열
  - `order_by` *(선택, list[dict])*: 정렬 조건 배열
  - `limit` *(선택, int, 기본값 50)*: 조회 제한 건수

#### (2) `query_table_pg`
- **설명**: PostgreSQL 원천 DB에 직접 비동기 쿼리를 실행합니다 (`asyncpg`). 사전에 `set_credentials` 또는 기동 환경변수로 해당 소스의 ID/PW가 설정되어 있어야 합니다.
- **파라미터**: `query_table`과 동일
- **응답 내 `via`**: `"postgres-direct"`

#### (3) `query_table_tibero`
- **설명**: Tibero 7 Zeta 원천 DB에 JDBC를 통해 직접 쿼리를 실행합니다 (`LIMIT N` 지원). 사전에 `set_credentials` 설정과 컨테이너 내 `driver/tibero-jdbc.jar`가 준비되어 있어야 합니다.
- **파라미터**: `query_table`과 동일
- **응답 내 `via`**: `"tibero-direct"`

---

### 4.3 테이블 데이터 집계 도구

#### (1) `aggregate_table`
- **설명**: 단일 테이블에 대해 집계 함수(`count`, `sum`, `avg`, `max`, `min`) 및 그룹화(Group By) 쿼리를 조립하여 MindsDB를 통해 실행합니다.
- **파라미터**:
  - `source_name` *(필수, string)*
  - `schema_name` *(필수, string)*
  - `table_name` *(필수, string)*
  - `func` *(필수, string)*: `count` | `sum` | `avg` | `max` | `min`
  - `column` *(선택, string)*: 집계 대상 컬럼 (`count` 시 생략 가능)
  - `group_by` *(선택, list[string])*: 그룹화 기준 컬럼 목록
  - `filters` *(선택, list[dict])*: 사전 필터 조건
  - `limit` *(선택, int, 기본값 50)*: 그룹 결과 행 제한

#### (2) `aggregate_table_pg`
- **설명**: 원천 PostgreSQL에 집계 쿼리를 직접 실행합니다 (`set_credentials` 필요).
- **파라미터**: `aggregate_table`과 동일
- **응답 내 `via`**: `"postgres-direct"`

#### (3) `aggregate_table_tibero`
- **설명**: 원천 Tibero에 집계 쿼리를 JDBC로 직접 실행합니다 (`set_credentials` 필요).
- **파라미터**: `aggregate_table`과 동일
- **응답 내 `via`**: `"tibero-direct"`

---

### 4.4 테이블 결합(Join) 도구

#### `join_tables`
- **설명**: 1단계 마스터/코드(left) 테이블의 조건 검색 결과에서 조인 키 목록을 추출한 뒤, 2단계 팩트/집계(right) 테이블의 `WHERE IN (...)` 절로 자동 주입하여 조회하고 MCP 프로세스 메모리 내에서 결합합니다. DB 엔진 간 물리 조인 쿼리를 날리지 않으며, 양쪽 테이블의 키가 빗나가는 현상을 원천 방지합니다.
- **멀티턴 정제 유도 (`TOO_MANY_CANDIDATES`)**: 1단계에서 추출된 키 개수가 `max_in_keys`(기본 100건)를 초과하면 무리하게 2단계 조회를 실행하지 않고, 후보 수량과 샘플 및 되묻기 안내 메시지를 반환하여 에이전트가 사용자에게 범위를 좁히도록 되묻게 유도합니다.
- **파라미터**:
  - `left_source_name`, `left_schema_name`, `left_table_name` *(필수, string)*
  - `left_on` *(필수, string | list[string])*: 왼쪽 테이블 조인 키 컬럼
  - `right_source_name`, `right_schema_name`, `right_table_name` *(필수, string)*
  - `right_on` *(필수, string | list[string])*: 오른쪽 테이블 조인 키 컬럼
  - `left_via` *(선택, string, 기본값 `"mindsdb"`)*: `"mindsdb"` | `"pg"` | `"tibero"`
  - `right_via` *(선택, string, 기본값 `"mindsdb"`)*: `"mindsdb"` | `"pg"` | `"tibero"`
  - `left_columns`, `right_columns` *(선택, list[string])*: 각 면의 출력 컬럼 (조인 키는 자동 포함)
  - `left_filters`, `right_filters` *(선택, list[dict])*: 각 면의 사전 필터
  - `left_limit`, `right_limit` *(선택, int, 기본값 50)*: 각 면의 조회 행 상한
  - `how` *(선택, string, 기본값 `"inner"`)*: `"inner"` | `"left"`
  - `max_in_keys` *(선택, int, 기본값 100)*: 2단계 WHERE IN 절 주입 최대 키 수 한도
- **응답 필드 예시 (정상 결합)**:
  ```json
  {
    "via": "mcp-assemble",
    "how": "inner",
    "status": "SUCCESS",
    "left": { "source_name": "...", "table_name": "...", "on": ["site_cd"], "fetched": 2 },
    "right": { "source_name": "...", "table_name": "...", "on": ["site_cd"], "fetched": 2 },
    "row_count": 2,
    "items": [
      {
        "left": { "site_cd": "S01", "site_name": "팔당정수장" },
        "right": { "site_cd": "S01", "val": 12.3 }
      }
    ]
  }
  ```
- **응답 필드 예시 (후보 과다로 멀티턴 되묻기 유도 시)**:
  ```json
  {
    "via": "mcp-assemble",
    "how": "inner",
    "status": "TOO_MANY_CANDIDATES",
    "candidate_count": 142,
    "threshold": 100,
    "sample_candidates": ["S01", "S02", "S03", "S04", "S05"],
    "message": "1단계 마스터 검색 결과 조인 키 'site_cd'의 대상이 142건으로 안전 상한(100건)을 초과했습니다. WHERE IN 절 과부하를 방지하기 위해 2단계 조회를 중단합니다. 사용자에게 권역(지사), 시설명 등 조건을 구체화하도록 되물어보세요.",
    "left": { "source_name": "...", "table_name": "...", "on": ["site_cd"], "fetched": 142 },
    "right": null,
    "row_count": 0,
    "items": []
  }
  ```

---

### 4.5 자격 증명(인증) 관리 도구

#### (1) `set_credentials`
- **설명**: 원천 DB 직조회(`*_pg`, `*_tibero`)에 필요한 로그인 정보(ID/PW)를 현재 실행 중인 MCP 프로세스 메모리에 저장합니다. 응답에는 보안상 비밀번호가 제외됩니다.
- **파라미터**:
  - `source_name` *(필수, string)*: 대상 데이터소스 이름
  - `user` *(필수, string)*: DB 사용자 계정
  - `password` *(필수, string)*: DB 비밀번호

#### (2) `clear_credentials`
- **설명**: 메모리에 저장된 자격 증명을 삭제합니다.
- **파라미터**:
  - `source_name` *(선택, string)*: 지정 소스만 제거 (생략 시 메모리의 모든 계정 제거)

---

## 5. 관리 및 진단 엔드포인트

- **커스텀 라우트**: `GET /health`
  - stone-meta 카탈로그(`POST /meta/catalog`), MindsDB 실행기(`POST /query_execute`), `nk-backend` 데이터소스 엔드포인트의 통신 상태를 종합 점검합니다.
- **전송 계층**:
  - `streamable-http`: `/mcp` 엔드포인트 (기본 포트 8111, Nginx 프록시 연동 시 8096/mcp)
  - 인증: HTTP Header `X-Api-Key: <MCP_API_KEYS>`
