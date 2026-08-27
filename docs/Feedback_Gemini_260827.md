PostgreSQL 분석용 MCP 서버(kair-mcp-query)의 도구(Tool) 구성을 고도화해 주세요.
AI 에이전트가 데이터베이스 구조를 정확히 파악하고, 복잡한 통계/조회 쿼리를 안전하게 수행할 수 있도록 아래 사양에 맞춰 도구들을 추가 및 개선해 주시기 바랍니다.

---

### [기본 원칙 및 안전장치 (Security & Guardrails)]
1. **전송 방식 유지**: 기존처럼 `--transport stdio`와 `streamable-http` 방식을 모두 지원하도록 유지해 주세요.
2. **읽기 전용(Read-Only) 강제**: 
   - 모든 쿼리는 Read-Only 세션(`SET TRANSACTION READ ONLY`)으로 실행되어야 합니다.
   - `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `GRANT` 등 DML/DDL은 원천 차단하고 `SELECT`만 허용합니다.
3. **타임아웃 및 하드 리밋(Hard Limit)**:
   - 쿼리 실행 타임아웃: 최대 15초 (`SET statement_timeout = '15s'`)
   - 조회 행수 상한: 클라이언트가 요청한 limit과 무관하게 최대 1,000건으로 상한선 고정 (`limit = min(limit, 1000)`)

---

### [구현해야 할 MCP 도구(Tools) 목록]

1. `list_tables` (기존 유지/개선)
   - **기능**: 접근 가능한 테이블 및 뷰(View) 목록과 간단한 테이블 설명 반환
   - **인자**: 없음 (또는 `schema_name` 필터 옵션)

2. `describe_table` (신규 추가 - 필수)
   - **기능**: 특정 테이블의 상세 컬럼 메타데이터 반환 (컬럼명, 데이터 타입, Nullable 여부, PK 여부, 컬럼 한글 코멘트/설명)
   - **인자**:
     - `source_name` (string, required)
     - `schema_name` (string, required)
     - `table_name` (string, required)

3. `get_distinct_values` (신규 추가)
   - **기능**: 특정 컬럼의 고유값 목록 조회 (코드성 컬럼, 상태값, 구분자 등의 실제 적재 값 확인용)
   - **인자**:
     - `source_name` (string, required)
     - `schema_name` (string, required)
     - `table_name` (string, required)
     - `column_name` (string, required)
     - `limit` (integer, optional, default: 50, max: 200)

4. `query_table` (기존 유지/개선)
   - **기능**: 조건(WHERE), 정렬(ORDER BY), 컬럼 선택을 통한 기본 데이터 조회
   - **인자**:
     - `source_name`, `schema_name`, `table_name` (string, required)
     - `columns` (array of strings, optional)
     - `where_clause` (string or dict, optional, SQL 인젝션 안전 파라미터 처리)
     - `order_by` (string, optional, e.g. "created_at DESC")
     - `limit` (integer, optional, default: 50, max: 1000)

5. `aggregate_table` (기존 유지)
   - **기능**: 테이블의 기본 통계 및 집계 (`count`, `sum`, `avg`, `min`, `max`) 및 `group_by` 수행
   - **인자**:
     - `source_name`, `schema_name`, `table_name` (string, required)
     - `func` (string, required: "count" | "sum" | "avg" | "min" | "max")
     - `column` (string, optional, count일 경우 null 허용)
     - `group_by` (array of strings, optional)
     - `limit` (integer, optional, default: 50)

6. `execute_read_only_sql` (신규 추가 - 필수)
   - **기능**: 다중 테이블 JOIN, 윈도우 함수, 서브쿼리, 시계열 리샘플링 등 복잡한 분석을 위한 순수 `SELECT` SQL 실행
   - **인자**:
     - `sql_query` (string, required, 오직 SELECT 문만 허용)
     - `params` (dict or array, optional, 파라미터 바인딩)
     - `limit` (integer, optional, default: 100, max: 1000)

---

위 사양에 맞춰 도구 스키마 및 핸들러 코드를 구현하고, Docker 컨테이너를 재빌드해 주세요.