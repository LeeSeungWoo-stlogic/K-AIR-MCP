# Change log

K-AIR MCP 업데이트 이력입니다. 서비스 설명·기능 안내는 [`README.md`](README.md)를 봅니다.

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
- Tibero SQL은 `FETCH FIRST n ROWS ONLY`

관련: `app/engine.py` · `app/intersect.py` · `app/tb_store.py` · `tests/test_engine.py` · `tests/test_intersect.py`

### Tibero JDBC 조회 · 카탈로그 선행

카탈로그 `sources[].engine`을 먼저 읽고 그 엔진 원천만 연다. 분석 Postgres가 없거나 5434가 꺼져 있으면 짧게 실패하고 기동을 유지한다. Tibero는 `driver/tibero-jdbc.jar`를 `/opt/tibero/jdbc/tibero7-jdbc.jar`에 mount한 뒤 JDBC thin으로 같은 조회 도구를 실행한다. 이미지에 JRE와 JayDeBeApi를 넣는다. JAR은 Git에 없다.

관련: `app/tb_store.py` · `app/tools.py` · `app/main.py` · `app/settings.py` · `docker-compose.yml` · `Dockerfile` · `driver/README.md`

### 문서

- `README.md`는 서비스·기능 안내
- 날짜별 작업 요약은 이 파일
