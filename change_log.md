# Change log

K-AIR MCP Analyze 업데이트 이력입니다. 서비스 설명·기능 안내는 [`README.md`](README.md)를 봅니다.

## 2026-09-16

### 카탈로그 목록과 상세를 나눈다

`POST /meta/catalog`는 소스·표 이름만 페이지로 받는다(`limit` 기본 50, `cursor`). 컬럼·FK는 요청 경로에서 접지 않는다. `list_tables`는 이름 목록이다. `describe_table`은 `POST /meta/table`, `list_join_hints`는 표 키를 받아 `POST /meta/ref` 한 번만 친다. 전 표 N+1은 하지 않는다. 빈 `columns` 표도 목록에 남긴다. 조회 도구는 `/meta/table`로 컬럼을 채운 뒤 `/query_execute`를 친다.

관련: `app/catalog_client.py` · `app/intersect.py` · `app/tools.py` · `app/main.py` · `tests/test_catalog_paging.py` · `tests/test_describe_table_meta.py`

### MCP `/health`는 카탈로그 전체를 읽지 않는다

Docker healthcheck가 30초마다 MCP `GET /health`를 치고, 그 핸들러가 `POST /meta/catalog` 전체를 다시 받았다. stone-meta 워커가 하나라 그 조회가 안 끝나면 `/health`·`/data_decision`까지 멈췄다. `probe_catalog`는 stone `GET /health`만 본다. 표 목록은 도구가 부를 때만 `POST /meta/catalog`를 쓴다.

관련: `app/catalog_client.py` · `tests/test_health_probe.py`

### Tibero JDBC 직조회

`query_table_tibero` / `aggregate_table_tibero`를 둔다. 좌표는 nk-backend 데이터소스, 계정은 `set_credentials`. `driver/tibero-jdbc.jar`는 이미지 빌드에 넣는다. Git에는 올리지 않는다. 없으면 빌드가 실패한다. 조인 후보 메타는 카탈로그에 없어 힌트 경로에 넣지 않았다. `join_tables`의 `via=tibero`는 호출자가 준 키로 붙인다.

관련: `app/tibero_runner.py` · `app/sqlutil.py` · `app/tools.py` · `app/main.py` · `tests/test_tibero_direct.py`

### MCP에서 조회 결과 재조립

MindsDB 경유 도구는 그대로 둔다. `join_tables`가 두 표를 `query_table` 또는 `query_table_pg`로 가져온 뒤 프로세스 안에서 붙인다. 엔진에 JOIN SQL을 보내지 않는다. 조인 키는 호출자가 준다.

`/meta/catalog`는 `join_candidates`/`join_groups`/infer-FK를 내지 않는다. 컬럼 `references`·`referenced_by`만 있고, `list_join_hints`와 `describe_table`이 그 칸을 보여 준다.

관련: `app/assemble.py` · `app/tools.py` · `app/main.py` · `tests/test_assemble_join.py`

### stone-meta 전용 이미지와 프록시 한 포트

stone-meta는 `newkair-backend`를 베이스로 쓰지 않는 `deploy/stone-meta/Dockerfile`(`K-AIR-Stone`)로 띄운다. MCP는 이 저장소 이미지(`kair-mcp-analyze:dev`)로 따로 띄운다. 호스트 한 포트는 nginx가 `/mcp`만 MCP에, 나머지는 stone-meta에 넘긴다. 프로세스를 하나로 합치지 않는다.

관련: `Dockerfile` · `docker-compose.yml` · `K-AIR-Stone/deploy/stone-meta/`

## 2026-09-15

### stone-meta-api 카탈로그·실행 동기화

허용 표는 `stone-meta-api` `POST /meta/catalog`만 본다. `STONE_META_URL`을 쓰고, `ROBO_META_URL`은 별칭이다. 표별 `schema_name`을 쓰며 소스 `source_schema` 한 칸으로 덮지 않는다.

`query_table` · `aggregate_table` · `get_distinct_values`의 SELECT는 `POST /query_execute`(MindsDB)로 실행한다. 3단 수식은 카탈로그 소스명·표 스키마·표 이름을 유지한다.

관련: `app/catalog_client.py` · `app/execute_client.py` · `app/intersect.py` · `app/sqlutil.py` · `app/tools.py` · `app/settings.py` · `app/main.py`

### Postgres 직조회 `query_table_pg`

MindsDB를 거치지 않는 조립 SELECT를 둔다. 접속 좌표는 nk-backend `GET /air-swmm/data-fabric/api/datasources`에서 읽고, 스키마는 카탈로그 표 단위다. id/pw는 `set_credentials` 또는 `MCP_DS_USER_<소스>` / `MCP_DS_PASSWORD_<소스>`다. 카탈로그·데이터소스 목록에 비밀번호를 넣지 않는다.

관련: `app/pg_runner.py` · `app/sources_client.py` · `app/credentials.py` · `app/tools.py` · `app/main.py` · `tests/test_sqlutil_paths.py` · `tests/test_intersect_schema.py` · `tests/test_credentials_env.py`

### 다른 PC HTTP 등록

같은 네트워크 클라이언트는 SSH·cwd·로컬 Docker 없이 `http://<MCP호스트>:8111/mcp` + `x-api-key`만 넣는다. 컨테이너는 대상 호스트 `nk-net`의 `kair-mcp-analyze`다.

관련: `mcp.cursor.example.json` · `mcp.cursor.http.example.json` · `docker-compose.yml` · `README.md`

문서: `README.md` — 실행 경로 둘, HTTP 등록, `query_table_pg` 자격 증명.

### MindsDB 경로 식별자 방언

`aggregate_table`·`query_table`·`get_distinct_values`가 컬럼을 `"suj_name"`처럼 쌍따옴표로 묶어 `/query_execute`에 넘겼다. MindsDB(MySQL 방언)는 이를 식별자가 아니라 문자열로 보아 `WHERE`가 항상 거짓이고 COUNT가 0이었다. 그 경로는 백틱만 쓴다. PG 직조회는 기존 쌍따옴표를 유지한다.

관련: `app/sqlutil.py` · `tests/test_sqlutil_paths.py`

### PG 직조회 집계 `aggregate_table_pg`

`query_table_pg`만 있고 집계가 `/query_execute`에만 있으면 COUNT 등을 PG에서 할 수 없다. SELECT 전용은 INSERT/UPDATE/DDL 금지이지 집계 금지가 아니다. `count`/`sum`/`avg`/`max`/`min`과 `group_by`·`filters`를 원천 Postgres에 직접 실행한다.

관련: `app/tools.py` · `app/main.py` · `tests/test_sqlutil_paths.py`
