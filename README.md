# K-AIR MCP Analyze

에이전트가 데이터허브 **조회**를 하도록 여는 MCP 서버입니다. 카탈로그는 `stone-meta-api` `POST /meta/catalog`, 기본 실행은 `POST /query_execute`(MindsDB)입니다. 같은 서버에 원천 Postgres 직조회 도구(`query_table_pg`)를 둡니다. SQL 문자열은 직접 받지 않습니다.

stone-meta는 **별도 전용 이미지**입니다(`K-AIR-Stone/deploy/stone-meta/Dockerfile`, `newkair-backend` 베이스 아님). MCP는 이 저장소 이미지입니다. 호스트 한 포트는 nginx가 `/mcp`와 나머지 경로만 나눕니다.

**업데이트 이력:** [`change_log.md`](change_log.md)

## 최근 변경 (2026-09-16)

- **MCP `/health`.** stone `GET /health`만 본다. 30초 Docker healthcheck가 `POST /meta/catalog` 전체를 다시 받지 않는다. 표 목록은 도구 호출 때 읽는다.
- **이미지 둘.** stone-meta 전용 이미지 + MCP 이미지. 한 프로세스에 합치지 않는다.
- **한 포트.** nginx가 `/mcp` → MCP, 나머지 → stone-meta. 정본 `:8096`. 기존 등록용 `:8111`도 같은 프록시에 붙일 수 있다.
- **재조립.** `join_tables`는 각 면을 mindsdb/pg/tibero로 가져온 뒤 MCP에서 붙인다. 조인 키는 호출자가 준다. `/meta/catalog`에는 infer-FK·조인 후보 목록이 없다.
- **Tibero JDBC.** 이미지 빌드에 `driver/tibero-jdbc.jar`가 필요하다. Git에는 올리지 않는다.
- 상세는 [`change_log.md`](change_log.md) 2026-09-16.

## 이 서비스가 하는 일

- REST: stone-meta 컨테이너의 계약 경로. 접두어 없음. 프록시 뒤에서 연다.
- 에이전트: 소스 목록·표 목록·컬럼 상세·고유값·제한 SELECT·집계 도구.
- 허용 표 = `POST /meta/catalog`에 있는 Postgres 표·컬럼.
- MCP HTTP는 Streamable HTTP(`/mcp`) + `X-Api-Key`. REST 계약 경로는 키를 요구하지 않는다.
- `query_table`(MindsDB)에는 DB 비밀번호가 필요 없습니다. `query_table_pg`만 계정(id/pw)이 필요합니다. 도구 결과에 비밀번호는 없습니다.

하지 않는 일: 자유 SQL 문자열, INSERT/UPDATE/DELETE/DDL, dump, 카탈로그에 없는 표 조회. `count`/`sum`/`avg`/`max`/`min`은 SELECT 집계라 양쪽 경로에 있다.

## 경로

| 면 | 경로 | 컨테이너 | 호스트 |
| --- | --- | --- | --- |
| stone-meta 계약 | `/health`, `/meta/catalog`, `/query_execute`, `/data_decision`, `/t2sql` | `stone-meta-api:8096` | 프록시 `:8096` |
| MCP | `/mcp` | `kair-mcp-analyze:8111` | 프록시 `:8096/mcp` |

## 도구

| 도구 | 역할 |
| --- | --- |
| `list_sources` | 카탈로그 소스·스키마와 data-fabric host/port/db. 비밀번호 없음 |
| `list_tables` | 허용 표 목록. 물리 3키와 논리명·설명. 선택 `schema_name` |
| `describe_table` | 표 논리명·설명, 컬럼 타입·PK·논리명·코멘트, `references`/`referenced_by` |
| `list_join_hints` | 카탈로그 FK(`references`)만 모은다. infer-FK·논리 동일 표는 없음 |
| `get_distinct_values` | 허용 컬럼 DISTINCT. `/query_execute`. 별칭 `distinct_value` |
| `query_table` | 조립 SELECT를 `/query_execute`(MindsDB)로 실행 |
| `query_table_pg` | 같은 조립 SELECT를 원천 Postgres에 직접 실행. `set_credentials` 필요 |
| `query_table_tibero` | 같은 조립 SELECT를 원천 Tibero에 JDBC 직조회. `set_credentials` 필요 |
| `aggregate_table` | `count`/`sum`/`avg`/`max`/`min`. `/query_execute` |
| `aggregate_table_pg` | 같은 집계를 원천 Postgres에 직접 실행. `set_credentials` 필요 |
| `aggregate_table_tibero` | 같은 집계를 원천 Tibero에 JDBC 직조회. `set_credentials` 필요 |
| `join_tables` | 두 표를 mindsdb/pg/tibero로 조회한 뒤 MCP에서 붙인다. JOIN SQL을 엔진에 보내지 않음. 조인 키는 호출자가 줌 |
| `set_credentials` | PG 직조회용 id/pw. 프로세스 메모리. 결과에 비밀번호 없음 |
| `clear_credentials` | 넣어 둔 계정 삭제 |

행 상한은 `MCP_ROW_LIMIT`(기본 200). `filters.op`: eq, ne, gt, gte, lt, lte, like, in, is_null, is_not_null.

## 실행 경로

| 도구 | 창구 | 비밀번호 |
| --- | --- | --- |
| `query_table` / `aggregate_table` 등 | stone-meta `POST /query_execute` → MindsDB | 없음 |
| `query_table_pg` / `aggregate_table_pg` | nk-backend 데이터소스 좌표 → asyncpg | `set_credentials` 또는 `MCP_DS_USER_<소스>` / `MCP_DS_PASSWORD_<소스>` |
| `query_table_tibero` / `aggregate_table_tibero` | nk-backend 데이터소스 좌표 → Tibero JDBC | 위와 같음. 이미지에 `driver/tibero-jdbc.jar` 필요 |
| `join_tables` | 위 경로로 두 번 조회한 뒤 MCP 프로세스에서 조인 | 면이 pg이면 해당 면만 필요 |

접속 좌표(host/port/database)는 데이터소스 API에서 읽습니다. 카탈로그에 넣지 않습니다. 스키마는 카탈로그 표 단위입니다. PG 직조회는 여전히 `nk-backend`가 필요합니다.

## 구성

```text
app/                          FastMCP 서버 (stdio / Streamable HTTP)
tests/                        단위 테스트
Dockerfile                    MCP 전용
docker-compose.yml            MCP + nginx 프록시
mcp.cursor.example.json       다른 PC HTTP 등록
```

전제: `stone-meta-api`, `nk-backend`, `nk-net`. 필수 설정은 `MCP_API_KEYS`와 `STONE_META_URL`. Tibero 직조회는 `driver/tibero-jdbc.jar`가 빌드에 있어야 한다. Git 미포함. 설명은 [`driver/README.md`](driver/README.md).

## 실행

```powershell
copy .env.example .env
# MCP_API_KEYS 필수. 따옴표 넣지 않음
# STONE_ROOT 가 K-AIR-Stone 루트가 아니면 지정
docker compose up -d --build
curl.exe -fsS http://127.0.0.1:8096/health
curl.exe -fsS http://127.0.0.1:8096/mcp
```

프록시 `GET /health`는 stone-meta 계약입니다. MCP 컨테이너 `GET /health`는 프로세스·의존 연결만 봅니다(stone `/health`, datasources). 카탈로그 전체를 받지 않습니다. MCP 도구는 `/mcp`입니다.

```powershell
python -m app.main --transport http
```

## MCP 등록

다른 PC(권장). SSH·Docker·소스 경로·cwd는 넣지 않습니다. 그 PC가 호스트 `:8096`에 닿으면 됩니다.

```json
{
  "mcpServers": {
    "kair-analyze": {
      "url": "http://<호스트>:8096/mcp",
      "headers": {
        "x-api-key": "<MCP_API_KEYS 값만>"
      }
    }
  }
}
```

이미 `:8111/mcp`로 등록한 클라이언트는 compose가 `8111:8096`을 열면 그대로 됩니다.

같은 MCP JSON에 다른 서버를 둘 때는 `mcpServers`를 한 번만 씁니다.

같은 호스트에서 컨테이너 stdio를 쓸 때만:

```json
{
  "mcpServers": {
    "kair-analyze": {
      "command": "docker",
      "args": ["exec", "-i", "stone-meta-api", "python", "-m", "app.main", "--transport", "stdio"]
    }
  }
}
```

`mcp.json`은 JSON이라 키를 `"…"`로 감쌉니다. 서버가 받는 API Key 값은 따옴표 없는 키입니다.

## 설정

`.env.example`을 Git에서 제외된 `.env`로 복사합니다. 비밀번호·API Key는 코드와 Git 추적 문서에 저장하지 않습니다.

| 변수 | 역할 |
| --- | --- |
| `MCP_API_KEYS` | MCP HTTP `X-Api-Key` / `x-api-key` |
| `STONE_META_URL` | `POST /meta/catalog`, `POST /query_execute`. 기본 `http://stone-meta-api:8096` |
| `ROBO_META_URL` | `STONE_META_URL`이 비면 이 값을 씀 |
| `NK_BACKEND_URL` | 데이터소스 목록. `query_table_pg`용 |
| `NK_BACKEND_TOKEN` | 데이터소스 API Bearer. 없으면 빈 값 |
| `MCP_ROW_LIMIT` | 행 상한 |
| `API_HOST` / `API_PORT` | MCP HTTP 바인드. 기본 `0.0.0.0:8111` |
| `MCP_DS_USER_<소스>` / `MCP_DS_PASSWORD_<소스>` | 선택. `query_table_pg` 기동 시 시드. id/pw를 문서에 박지 않음 |
| `STONE_ROOT` | compose 빌드 컨텍스트. 기본 `../K-AIR-Stone` |
| `STONE_BACKEND_ENV` | stone `backend/.env` 마운트 경로 |

## 테스트

```powershell
python -m pytest tests -q
```

## 알려진 이슈·한계

| 항목 | 설명 | 상태 |
| --- | --- | --- |
| **MindsDB 경로** | `query_table` 등은 `/query_execute` | 카탈로그 표만 조립 SELECT |
| **PG 직조회** | `query_table_pg` | 카탈로그 표만. id/pw는 클라이언트 세션 또는 env. nk-backend 필요 |
| **자유 SQL** | 임의 SELECT 문자열 | 넣지 않음 |
| **포털 키·감사** | 포털 원장 | 미구현 |

## 관련

- `stone-meta-api` — 이 이미지. `POST /meta/catalog`, `POST /query_execute`, `/mcp`
- `nk-backend` — `GET /air-swmm/data-fabric/api/datasources`. 앱 본체는 그대로 둔다
- `K-AIR-Stone` — 서빙 카탈로그·표별 `schema_name`. 빌드 시 backend만 복사
- `K-AIR-MCP` master — 기존 `kair-query`(robo-meta :8110)
