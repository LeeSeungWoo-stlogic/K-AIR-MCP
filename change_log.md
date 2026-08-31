# Change log

K-AIR MCP 업데이트 이력입니다. 서비스 설명·기능 안내는 [`README.md`](README.md)를 봅니다.

---

## 2026-08-31

### aggregate_table 필터

`aggregate_table`에 `query_table`과 같은 선택 `filters` `{column,op,value}`를 둔다. SQL은 `WHERE` 다음 `GROUP BY`.

관련: `app/sqlutil.py` · `app/tools.py` · `app/main.py`

### 행 상한 하드캡 해제

`MCP_ROW_LIMIT`를 서버가 200으로 자르지 않는다. env 값이 `query_table` · `aggregate_table` · `get_distinct_values` 상한이다.

관련: `app/settings.py` · `app/tools.py`

---

## 2026-08-28

### 실행면 `/query_execute`

`query_table` · `get_distinct_values` · `aggregate_table`의 SELECT를 데이터 Postgres 직접 실행에서 `robo-meta-api` `POST /query_execute`로 옮김. 도구 인자·`mcp.json` 등록은 그대로.

- SQL은 완성 문자열만. 식별자 백틱 3단 수식, 필터 리터럴 인라인, `LIMIT n`. `%s` 없음
- HTTP 오류와 본문 `status != ok`는 도구 오류. 빈 `rows`를 성공 `items=[]`로 바꾸지 않음
- `list_tables` · `describe_table` · `MCP_PG_*` 허용 게이트는 유지. `ROBO_META_URL`이 catalog·execute 공통

관련: `app/execute_client.py` · `app/sqlutil.py` · `app/tools.py` · `tests/test_execute_client.py`

문서: `README.md` — 실행면은 `/query_execute`, `MCP_PG_*`는 목록 게이트, `MCP_ROW_LIMIT`는 env 그대로.

---

## 2026-08-27

### 조회 MCP 서버

공식 Python SDK `mcp` FastMCP로 창구 하나를 둠. 포털 `POST /mcp` 목업을 정본으로 복제하지 않음.

- 전송: CLI 기본 **stdio**, compose는 **Streamable HTTP** `--transport http` · `/mcp`
- 도구: `list_tables` · `describe_table` · `get_distinct_values` · `query_table` · `aggregate_table`
- 허용 표 = `POST /meta/catalog` ∩ 엔진 원천 실존 표. 자유 SQL·`SELECT` 접두 검사 없음
- `filters`/`order_by`는 구조화 객체만. 행 상한 200. 읽기 전용·`statement_timeout` 15초
- HTTP `X-Api-Key` (`MCP_API_KEYS`). DB 비밀번호는 도구·등록 JSON에 없음

관련: `app/main.py` · `app/tools.py` · `app/sqlutil.py` · `docker-compose.yml`

### LAN HTTP

호스트 바인드를 `127.0.0.1:8110`에서 `0.0.0.0:8110`으로 바꿈. 다른 PC는 `http://<IP>:8110/mcp` + 키만 등록.

관련: `mcp.cursor.example.json` · `mcp.cursor.http.example.json`

### 카탈로그 engine 분기

`sources[].engine`으로 원천을 먼저 가름. 도구는 나누지 않음.

- `postgresql`/`postgres`/`postgis` → 마트(Postgres)
- `tibero`/`oracle` → 수집 Tibero. 같은 스키마·표 이름이 Postgres에 있어도 섞지 않음
- 엔진 없음·미지원 값은 목록에서 제외
- Tibero SQL은 `FETCH FIRST n ROWS ONLY`. JDBC 실행은 아직 없음(로컬 원천 없음)

관련: `app/engine.py` · `app/intersect.py` · `app/tb_store.py` · `tests/test_engine.py` · `tests/test_intersect.py`

### 문서

- `README.md`는 서비스·기능 안내
- 날짜별 작업 요약은 이 파일
