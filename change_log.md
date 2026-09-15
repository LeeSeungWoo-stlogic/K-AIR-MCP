# Change log

K-AIR MCP Analyze 업데이트 이력입니다. 서비스 설명·기능 안내는 [`README.md`](README.md)를 봅니다.

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
