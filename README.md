# K-AIR MCP Analyze

에이전트가 데이터허브 **조회**를 하도록 여는 MCP 서버입니다. 카탈로그는 `stone-meta-api` `POST /meta/catalog`, 기본 실행은 `stone-meta-api` `POST /query_execute`(MindsDB)입니다. 같은 서버에 원천 Postgres 직조회 도구(`query_table_pg`)를 둡니다. SQL 문자열은 직접 받지 않습니다.

**업데이트 이력:** [`change_log.md`](change_log.md)

## 최근 변경 (2026-09-15)

- **카탈로그 SoT를 stone-meta-api로.** `ROBO_META_URL` 별칭은 유지한다. 표별 `schema_name`을 쓴다. 소스 `source_schema` 한 칸으로 덮지 않는다.
- **실행 경로 둘.** `query_table` / `aggregate_table` / `get_distinct_values`는 `/query_execute`. `query_table_pg`는 nk-backend 데이터소스 host/port/db로 asyncpg.
- **등록.** 다른 PC는 SSH·소스 경로 없이 `http://<MCP호스트>:8111/mcp` + `x-api-key`.
- 상세는 [`change_log.md`](change_log.md) 2026-09-15.

## 이 서비스가 하는 일

- 에이전트에 소스 목록·표 목록·컬럼 상세·고유값·제한 SELECT·집계 도구를 줍니다.
- 허용 표 = `POST /meta/catalog`에 있는 Postgres 표·컬럼.
- HTTP는 Streamable HTTP(`/mcp`) + `X-Api-Key`. 같은 호스트 stdio는 컨테이너 `docker exec`.
- `query_table`(MindsDB)에는 DB 비밀번호가 필요 없습니다. `query_table_pg`만 계정(id/pw)이 필요합니다. 도구 결과에 비밀번호는 없습니다.

하지 않는 일: 자유 SQL, DML/DDL, dump, 카탈로그에 없는 표 조회.

## 도구

| 도구 | 역할 |
| --- | --- |
| `list_sources` | 카탈로그 소스·스키마와 data-fabric host/port/db. 비밀번호 없음 |
| `list_tables` | 허용 표 목록. 물리 3키와 논리명·설명. 선택 `schema_name` |
| `describe_table` | 표 논리명·설명, 컬럼 타입·PK·논리명·코멘트 |
| `get_distinct_values` | 허용 컬럼 DISTINCT. `/query_execute`. 별칭 `distinct_value` |
| `query_table` | 조립 SELECT를 `/query_execute`(MindsDB)로 실행 |
| `query_table_pg` | 같은 조립 SELECT를 원천 Postgres에 직접 실행. `set_credentials` 필요 |
| `aggregate_table` | `count`/`sum`/`avg`/`max`/`min`. `/query_execute` |
| `set_credentials` | `query_table_pg`용 id/pw. 프로세스 메모리. 결과에 비밀번호 없음 |
| `clear_credentials` | 넣어 둔 계정 삭제 |

행 상한은 `MCP_ROW_LIMIT`(기본 200). `filters.op`: eq, ne, gt, gte, lt, lte, like, in, is_null, is_not_null.

## 실행 경로

| 도구 | 창구 | 비밀번호 |
| --- | --- | --- |
| `query_table` 등 | stone-meta `POST /query_execute` → MindsDB | 없음 |
| `query_table_pg` | nk-backend `GET /air-swmm/data-fabric/api/datasources` 좌표 → asyncpg | `set_credentials` 또는 `MCP_DS_USER_<소스>` / `MCP_DS_PASSWORD_<소스>` |

접속 좌표(host/port/database)는 데이터소스 API에서 읽습니다. 카탈로그에 넣지 않습니다. 스키마는 카탈로그 표 단위입니다.

## 구성

```text
app/                          FastMCP 서버 (stdio / Streamable HTTP)
tests/                        단위 테스트
docker-compose.yml            nk-net, http :8111
mcp.cursor.example.json       다른 PC HTTP 등록
mcp.cursor.http.example.json  HTTP 등록 사본
```

전제: `stone-meta-api`, `nk-backend`, `nk-net`. 필수 설정은 `MCP_API_KEYS`와 `STONE_META_URL`.

## 실행

```powershell
copy .env.example .env
# MCP_API_KEYS 필수. 따옴표 넣지 않음
docker compose up -d --build
curl.exe -fsS http://127.0.0.1:8111/health
```

헬스 본문은 `stone_catalog` / `stone_execute` / `nk_datasources`(ok/unreachable)입니다.

컨테이너 HTTP:

```powershell
python -m app.main --transport http
```

## MCP 등록

다른 PC(권장). SSH·Docker·소스 경로·cwd는 넣지 않습니다. 그 PC가 MCP 호스트 `:8111`에 닿으면 됩니다.

```json
{
  "mcpServers": {
    "kair-analyze": {
      "url": "http://<MCP띄운호스트>:8111/mcp",
      "headers": {
        "x-api-key": "<MCP_API_KEYS 값만>"
      }
    }
  }
}
```

같은 MCP JSON에 다른 서버를 둘 때는 `mcpServers`를 한 번만 씁니다.

같은 호스트에서 컨테이너 stdio를 쓸 때만:

```json
{
  "mcpServers": {
    "kair-analyze": {
      "command": "docker",
      "args": ["exec", "-i", "kair-mcp-analyze", "python", "-m", "app.main", "--transport", "stdio"]
    }
  }
}
```

`mcp.json`은 JSON이라 키를 `"…"`로 감쌉니다. 서버가 받는 API Key 값은 따옴표 없는 키입니다.

## 설정

`.env.example`을 Git에서 제외된 `.env`로 복사합니다. 비밀번호·API Key는 코드와 Git 추적 문서에 저장하지 않습니다.

| 변수 | 역할 |
| --- | --- |
| `MCP_API_KEYS` | HTTP `X-Api-Key` / `x-api-key` |
| `STONE_META_URL` | `POST /meta/catalog`, `POST /query_execute`. 기본 `http://stone-meta-api:8096` |
| `ROBO_META_URL` | `STONE_META_URL`이 비면 이 값을 씀 |
| `NK_BACKEND_URL` | 데이터소스 목록. `query_table_pg`용 |
| `NK_BACKEND_TOKEN` | 데이터소스 API Bearer. 없으면 빈 값 |
| `MCP_ROW_LIMIT` | 행 상한 |
| `API_HOST` / `API_PORT` | HTTP 바인드. 기본 `0.0.0.0:8111` |
| `MCP_DS_USER_<소스>` / `MCP_DS_PASSWORD_<소스>` | 선택. `query_table_pg` 기동 시 시드. id/pw를 문서에 박지 않음 |

## 테스트

```powershell
python -m pytest tests -q
```

## 알려진 이슈·한계

| 항목 | 설명 | 상태 |
| --- | --- | --- |
| **MindsDB 경로** | `query_table` 등은 `/query_execute` | 카탈로그 표만 조립 SELECT |
| **PG 직조회** | `query_table_pg` | 카탈로그 표만. id/pw는 클라이언트 세션 또는 env |
| **자유 SQL** | 임의 SELECT 문자열 | 넣지 않음 |
| **포털 키·감사** | 포털 원장 | 미구현 |

## 관련

- `stone-meta-api` — `POST /meta/catalog`, `POST /query_execute`
- `nk-backend` — `GET /air-swmm/data-fabric/api/datasources`
- `K-AIR-Stone` — 서빙 카탈로그·표별 `schema_name`
- `K-AIR-MCP` master — 기존 `kair-query`(robo-meta :8110)
