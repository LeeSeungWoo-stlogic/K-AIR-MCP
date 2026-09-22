# K-AIR MCP Analyze

에이전트가 데이터허브 **조회**를 하도록 여는 MCP 서버입니다. 카탈로그는 `stone-meta-api` `POST /meta/catalog`, 기본 실행은 `POST /query_execute`(MindsDB)입니다. 같은 서버에 원천 Postgres·Tibero 직조회 도구(`query_table_pg`, `query_table_tibero` 등)를 둡니다. SQL 문자열은 직접 받지 않습니다.

stone-meta는 **별도 전용 이미지**입니다(`K-AIR-Stone/deploy/stone-meta/Dockerfile`, `newkair-backend` 베이스 아님). MCP는 이 저장소 이미지(`kair-mcp-analyze`)입니다. 이 저장소의 `docker-compose.yml`은 **MCP 컨테이너 하나만** 띄우고 호스트 `:8111`을 엽니다. nginx 같은 앞단 프록시는 이 저장소에 없습니다.

**업데이트 이력:** [`change_log.md`](change_log.md)

## 최근 변경 (2026-09-22)

- **Tibero 7 Zeta LIMIT 지원.** 기존 ROWNUM 인라인 뷰 서브쿼리 래핑을 제거하고, Tibero 7 Zeta에서 공식 지원하는 `LIMIT N` 구문을 직접 적용.
- **`join_tables` 2단계 WHERE IN 주입.** 1단계 마스터(left) 조건 검색 결과에서 키를 추출해 2단계 팩트(right)의 `WHERE IN (...)` 절로 자동 주입.
- **멀티턴 정제 유도 (`TOO_MANY_CANDIDATES`).** 1단계 조인 키 개수가 `max_in_keys`(기본 100건)를 초과하면 2단계 조회를 중단하고 안내 메시지 및 샘플 후보를 반환하여, 에이전트가 사용자에게 조건을 구체화하도록 되묻게 유도.
- 상세는 [`change_log.md`](change_log.md) 2026-09-22.

## 최근 변경 (2026-09-17)

- **계정 범위.** `set_credentials` 계정은 호출한 API Key 범위에만 들어가고 `MCP_CREDENTIALS_TTL_S`(기본 8시간) 뒤 사라진다. 다른 키는 볼 수 없다. 운영자 env 계정은 서버 공통 기본값이다.
- **직조회 한도.** Tibero에 로그인·문장·바깥 시간 한도가 걸린다. PG·Tibero 직조회는 `MCP_DIRECT_MAX_CONCURRENCY`(기본 4)를 함께 나눠 쓴다. 두 경로 모두 읽기 전용 연결이다.
- **헬스.** `/health`는 의존 서비스를 부르지 않는 생존 확인. `/health/ready`는 의존 서비스를 확인하고 필수가 안 되면 503.
- **카탈로그 캐시.** `MCP_CATALOG_TTL_S`(기본 300초) 동안 목록을 재사용한다. 페이지 크기 200.
- **Tibero JAR 선택.** JAR 없이도 이미지가 빌드된다. 없으면 Tibero 도구만 `Tibero JDBC 드라이버 미탑재` 오류.
- 상세는 [`change_log.md`](change_log.md) 2026-09-17.

## 이 서비스가 하는 일

- 에이전트: 소스 목록·표 목록·컬럼 상세·고유값·제한 SELECT·집계·결과 재조립 도구.
- 허용 표 = `POST /meta/catalog` 이름 목록의 Postgres·Tibero 표. 컬럼은 `POST /meta/table`.
- MCP HTTP는 Streamable HTTP(`/mcp`) + API Key(`X-Api-Key`, `Authorization: ApiKey …` 또는 `Bearer …`). `/health`, `/health/ready`만 키 없이 연다.
- `query_table`(MindsDB)에는 DB 비밀번호가 필요 없습니다. 직조회(`*_pg`, `*_tibero`)만 계정(id/pw)이 필요합니다. 도구 결과에 비밀번호·원천 접속 좌표(host/port/db)는 없습니다.

하지 않는 일: 자유 SQL 문자열, INSERT/UPDATE/DELETE/DDL, dump, 카탈로그에 없는 표 조회. `count`/`sum`/`avg`/`max`/`min`은 SELECT 집계라 모든 경로에 있다.

## 경로

| 면 | 경로 | 컨테이너 | 호스트(compose) |
| --- | --- | --- | --- |
| MCP | `/mcp` | `kair-mcp-analyze:8111` | `:8111/mcp` |
| 생존 확인 | `GET /health` (키 없음, 의존 호출 없음) | 같음 | `:8111/health` |
| 준비 확인 | `GET /health/ready` (키 없음, 필수 의존 실패 시 503) | 같음 | `:8111/health/ready` |
| stone-meta 계약 | `/health`, `/meta/catalog`, `/meta/table`, `/meta/ref`, `/query_execute` | `stone-meta-api:8096` | 이 compose가 열지 않음 |

## 도구

| 도구 | 역할 |
| --- | --- |
| `list_sources` | 카탈로그 소스·엔진·스키마, 데이터소스 등록·활성 여부, 이 호출자에게 계정이 있는지(`credentials_set`, `credentials_origin`). 접속 좌표·계정명·비밀번호 없음 |
| `list_tables` | 허용 표 이름 목록. 물리 3키와 논리명·설명. 선택 `schema_name`. 컬럼은 없음 |
| `describe_table` | 표 논리명·설명, 컬럼 타입·PK·논리명·코멘트. `POST /meta/table` |
| `list_join_hints` | 한 표의 `/meta/ref` FK만. 표 키 필요. infer-FK 없음 |
| `get_distinct_values` | 허용 컬럼 DISTINCT. `/query_execute`. 별칭 `distinct_value` |
| `query_table` | 조립 SELECT를 `/query_execute`(MindsDB)로 실행 |
| `query_table_pg` | 같은 조립 SELECT를 원천 Postgres에 직접 실행. 계정 필요 |
| `query_table_tibero` | 같은 조립 SELECT를 원천 Tibero에 JDBC 직조회. 계정·JAR 필요 |
| `aggregate_table` | `count`/`sum`/`avg`/`max`/`min`. `/query_execute` |
| `aggregate_table_pg` | 같은 집계를 원천 Postgres에 직접 실행. 계정 필요 |
| `aggregate_table_tibero` | 같은 집계를 원천 Tibero에 JDBC 직조회. 계정·JAR 필요 |
| `join_tables` | 1단계 마스터 검색 키를 2단계 WHERE IN 절로 주입해 MCP에서 결합. 100건 초과 시 되묻기 유도(`TOO_MANY_CANDIDATES`) |
| `set_credentials` | 직조회용 id/pw. **이 API Key 범위**에만 두고 `MCP_CREDENTIALS_TTL_S` 뒤 만료. 결과에 비밀번호 없음 |
| `clear_credentials` | 이 API Key 범위의 계정만 삭제. env 기본값·다른 키는 그대로 |

행 상한은 `MCP_ROW_LIMIT`(기본 1000). `filters.op`: eq, ne, gt, gte, lt, lte, like, in, is_null, is_not_null. PG 직조회는 `/meta/table`의 컬럼 형(date, timestamp, numeric 등)에 맞춰 필터 값을 서버에서 변환한다.

## 실행 경로

| 도구 | 창구 | 계정 |
| --- | --- | --- |
| `query_table` / `aggregate_table` 등 | stone-meta `POST /query_execute` → MindsDB | 없음 |
| `query_table_pg` / `aggregate_table_pg` | nk-backend 데이터소스 좌표 → asyncpg (읽기 전용 트랜잭션) | 호출자 `set_credentials` > 운영자 `MCP_DS_USER_<소스>` / `MCP_DS_PASSWORD_<소스>` |
| `query_table_tibero` / `aggregate_table_tibero` | nk-backend 데이터소스 좌표 → Tibero JDBC (readOnly, 끝에 rollback) | 위와 같음. 이미지에 `driver/tibero-jdbc.jar` 필요 |
| `join_tables` | 위 경로로 두 번 조회한 뒤 MCP 프로세스에서 조인 | 면이 pg/tibero이면 해당 면만 필요 |

접속 좌표(host/port/database)는 데이터소스 API에서 서버 안에서만 읽습니다. 카탈로그·도구 결과에 넣지 않습니다. 스키마는 카탈로그 표 단위입니다. 직조회는 `nk-backend`가 필요합니다.

계정 범위: Streamable HTTP는 요청의 API Key를 sha256 해시한 값이 범위입니다(키 원문은 보관하지 않음). stdio는 로컬 한 사용자라 고정 범위 하나입니다. 조회 우선순위는 **호출자 범위 > env**입니다.

## 구성

```text
app/                          FastMCP 서버 (stdio / Streamable HTTP)
tests/                        단위 테스트
driver/                       Tibero JDBC JAR 자리(선택). README만 커밋
Dockerfile                    MCP 전용 이미지 (python:3.11.9-slim)
docker-compose.yml            MCP 컨테이너 하나 (nk-net external, 호스트 :8111)
mcp.cursor.example.json       다른 PC HTTP 등록
```

전제: `stone-meta-api`, `nk-backend`가 외부 도커 망 `nk-net`에 있어야 합니다. 필수 설정은 `MCP_API_KEYS`. Tibero 직조회는 `driver/tibero-jdbc.jar`가 빌드에 있어야 합니다(없어도 빌드는 됨). 설명은 [`driver/README.md`](driver/README.md).

## 실행

```powershell
copy .env.example .env
# MCP_API_KEYS 필수. 따옴표 넣지 않음
docker compose up -d --build
curl.exe -fsS http://127.0.0.1:8111/health
curl.exe -sS http://127.0.0.1:8111/health/ready
```

`GET /health`는 의존 서비스를 부르지 않고 즉시 200을 돌려줍니다. Docker healthcheck가 이 경로를 씁니다. `GET /health/ready`는 stone-meta `GET /health`(필수)와 nk-backend datasources(선택, 직조회용)를 동시에 각 3초 한도로 확인합니다. 필수가 안 되면 503, 선택만 안 되면 200 `degraded`. 항목별 상태는 `deps`에 있습니다.

로컬 실행:

```powershell
python -m app.main --transport http
```

폐쇄망 반입은 빌드한 이미지를 `docker save` → 반입 → `docker load`로 옮깁니다. 현장에서 pull·빌드하지 않습니다. 절차는 [`docs/GUIDE_OA_반입준비.md`](docs/GUIDE_OA_반입준비.md).

## MCP 등록

다른 PC(권장). SSH·Docker·소스 경로·cwd는 넣지 않습니다. 그 PC가 MCP 호스트 `:8111`에 닿으면 됩니다. 앞단 프록시를 따로 둔 환경이면 그 프록시의 `/mcp` URL을 씁니다.

```json
{
  "mcpServers": {
    "kair-analyze": {
      "url": "http://<MCP호스트>:8111/mcp",
      "headers": {
        "x-api-key": "<MCP_API_KEYS 값만>"
      }
    }
  }
}
```

같은 MCP JSON에 다른 서버를 둘 때는 `mcpServers`를 한 번만 씁니다.

같은 호스트에서 컨테이너 stdio를 쓸 때만(컨테이너 이름은 `kair-mcp-analyze`):

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

stdio는 `docker exec`마다 새 프로세스라 HTTP 서버와 계정 저장소를 공유하지 않습니다. `mcp.json`은 JSON이라 키를 `"…"`로 감쌉니다. 서버가 받는 API Key 값은 따옴표 없는 키입니다.

## 설정

`.env.example`을 Git에서 제외된 `.env`로 복사합니다. 비밀번호·API Key는 코드와 Git 추적 문서에 저장하지 않습니다.

| 변수 | 기본 | 역할 |
| --- | --- | --- |
| `MCP_API_KEYS` | (필수) | MCP HTTP API Key. 쉼표로 여러 개 |
| `STONE_META_URL` | `http://stone-meta-api:8096` (compose) | `POST /meta/catalog`, `/meta/table`, `/meta/ref`, `/query_execute` |
| `ROBO_META_URL` | | `STONE_META_URL`이 비면 이 값을 씀 |
| `NK_BACKEND_URL` | `http://nk-backend:8000` (compose) | 데이터소스 목록. 직조회용 |
| `NK_BACKEND_TOKEN` | 빈 값 | 데이터소스 API Bearer |
| `MCP_ROW_LIMIT` | `1000` | 행 상한 |
| `MCP_STATEMENT_TIMEOUT_MS` | `60000` | 직조회 문장 한도. PG `statement_timeout`, Tibero `setQueryTimeout`, MindsDB `timeout_s`(최대 120초) |
| `MCP_DIRECT_MAX_CONCURRENCY` | `4` | PG·Tibero 직조회 공용 동시 실행 수. 슬롯 대기도 문장 한도까지만 |
| `MCP_CREDENTIALS_TTL_S` | `28800` | `set_credentials` 계정 유효 시간(초) |
| `MCP_CATALOG_TTL_S` | `300` | 카탈로그 목록 캐시(초). `0`이면 매번 읽음 |
| `TIBERO_JDBC_JAR` | `/opt/tibero/jdbc/tibero-jdbc.jar` | Tibero JDBC JAR 경로 |
| `API_HOST` / `API_PORT` | `0.0.0.0` / `8111` | MCP HTTP 바인드 |
| `MCP_DS_USER_<소스>` / `MCP_DS_PASSWORD_<소스>` | | 선택. 운영자가 두는 서버 공통 직조회 계정. 모든 API Key가 기본값으로 씀. 호출자 `set_credentials`가 있으면 그쪽이 우선 |

## 테스트

```powershell
python -m pytest tests -q
```

JPype·JDBC는 테스트에서 가짜 객체로 대신합니다. 실제 DB에는 붙지 않습니다.

## 알려진 이슈·한계

| 항목 | 설명 | 상태 |
| --- | --- | --- |
| **MindsDB 경로** | `query_table` 등은 `/query_execute` | 카탈로그 표만 조립 SELECT |
| **직조회** | `*_pg`, `*_tibero` | 카탈로그 표만. 계정은 호출자 범위 또는 env. nk-backend 필요 |
| **Tibero 로그인 한도** | `DriverManager.setLoginTimeout`은 JVM이 뜬 뒤에만 걸림 | 첫 연결은 바깥 시간 한도(문장 한도 + 10초)가 막음 |
| **자유 SQL** | 임의 SELECT 문자열 | 넣지 않음 |
| **포털 키·감사** | 포털 원장 | 미구현 |

## 관련

- `stone-meta-api` — 별도 이미지. `POST /meta/catalog`, `/meta/table`, `/meta/ref`, `/query_execute`
- `nk-backend` — `GET /air-swmm/data-fabric/api/datasources`. 앱 본체는 그대로 둔다
- `K-AIR-Stone` — 서빙 카탈로그·표별 `schema_name`, stone-meta 배포
- `K-AIR-MCP` master — 기존 `kair-query`(robo-meta :8110)
