# K-AIR MCP

에이전트가 데이터허브 **조회**만 하도록 여는 공식 MCP 서버입니다. 창구는 하나이고, 카탈로그 소스 `engine`으로 Postgres(분석 마트)와 Tibero(수집)를 내부에서 가릅니다. SQL 문자열은 받지 않습니다.

도구 인자로 SELECT를 조립한 뒤 `robo-meta-api` `POST /query_execute`로 실행합니다. 에이전트에 SQL 문자열 도구는 없습니다. 포털 `POST /mcp` 목업을 정본으로 복제하지 않습니다.

**업데이트 이력:** [`change_log.md`](change_log.md)

## 이 서비스가 하는 일

- 에이전트에 표 목록·컬럼 상세·고유값·제한 SELECT·집계 도구를 줍니다.
- 허용 표 = `POST /meta/catalog` ∩ 해당 엔진 원천에 실존하는 표·컬럼.
- HTTP는 Streamable HTTP(` /mcp`) + `X-Api-Key`. stdio는 같은 PC IDE용입니다.
- AI는 MCP URL과 API Key만 압니다. DB 비밀번호·robo 주소는 도구 결과에 없습니다.

하지 않는 일: 자유 SQL, DML/DDL, dump/보내기, `t2s`·`argus_catalog` 데이터 조회, 엔진마다 MCP를 나누기.

## 도구

| 도구 | 역할 |
| --- | --- |
| `list_tables` | 허용 표 목록. 선택 `schema_name`. 응답에 `engine` |
| `describe_table` | 컬럼 타입·PK·코멘트. 없는 한글 설명은 빈 칸 |
| `get_distinct_values` | 허용 컬럼 DISTINCT. 상한은 `MCP_ROW_LIMIT` |
| `query_table` | 조립 SELECT. `columns`, `filters` `{column,op,value}`, `order_by` `{column,dir}` |
| `aggregate_table` | `count`/`sum`/`avg`/`max`/`min`. 선택 `filters` `{column,op,value}`. 전체 행 수는 `func=count` 그리고 column 없음 |

행 상한은 `MCP_ROW_LIMIT`(기본 200). 실행 SELECT는 `POST /query_execute`. 허용 확인용 Postgres는 읽기 전용·`statement_timeout` 15초. `filters.op`: eq, ne, gt, gte, lt, lte, like, in, is_null, is_not_null.

## 엔진 구분

`/meta/catalog`의 `sources[].engine`이 정본입니다. 에이전트가 엔진을 고르지 않습니다.

| 카탈로그 `engine` | 원천 |
| --- | --- |
| `postgresql` / `postgres` / `postgis` | 분석 마트 (로컬은 `kair-postgis-16`) |
| `tibero` / `oracle` | 수집 Tibero. OA에서 oracle로 적히는 경우가 있음 |

엔진이 없거나 모르는 값이면 목록에서 뺍니다. Tibero 표가 Postgres 실존 표와 이름이 같아도 섞지 않습니다.

도구는 카탈로그 `sources[].engine`을 먼저 읽고, 그 엔진 원천만 엽니다. Postgres 마트가 없어도 Tibero만으로 기동합니다. JDBC JAR는 이미지에 넣지 않고 `driver/tibero-jdbc.jar`를 mount합니다.

## 구성

```text
app/                 FastMCP 서버 (stdio / Streamable HTTP)
driver/              Tibero JDBC (`tibero-jdbc.jar`, Git 제외)
tests/               단위·계약 테스트
docker-compose.yml   네트워크용 http :8110
mcp.cursor.example.json       같은 PC stdio
mcp.cursor.http.example.json  다른 PC HTTP
```

전제: `robo-meta-api`와 `kair-metadata-platform_control-plane` 네트워크. 분석 마트는 선택(`MCP_PG_*`, 로컬은 호스트 5434). 수집 Tibero는 `driver/README.md`와 `MCP_TB_*`. 포털·OASIS는 이 저장소 범위가 아닙니다.

## 실행

```powershell
copy .env.example .env
# MCP_API_KEYS 필수. 따옴표 넣지 않음
# 분석 마트가 있으면 MCP_PG_* , Tibero면 driver/tibero-jdbc.jar 와 MCP_TB_*
docker compose up -d --build
curl.exe -fsS http://127.0.0.1:8110/health
```

헬스 `engines`는 실제로 열린 원천만 넣습니다. Tibero만 있으면 `["tibero"]`입니다.

같은 PC CLI(stdio, 기본):

```powershell
python -m app.main
```

컨테이너 HTTP:

```powershell
python -m app.main --transport http
```

## MCP 등록

같은 PC(권장 stdio). 컨테이너가 떠 있어야 합니다. URL·키·`.env`를 넣지 않습니다.

```json
{
  "mcpServers": {
    "kair-query": {
      "command": "docker",
      "args": ["exec", "-i", "kair-mcp-query", "python", "-m", "app.main", "--transport", "stdio"]
    }
  }
}
```

다른 PC(Streamable HTTP). DB 비밀번호는 넣지 않습니다.

```json
{
  "mcpServers": {
    "kair-query": {
      "url": "http://<MCP띄운PC의IP>:8110/mcp",
      "headers": {
        "X-Api-Key": "<MCP_API_KEYS 값만>"
      }
    }
  }
}
```

`mcp.json`은 JSON이라 키를 `"…"`로 감쌉니다. 서버가 받는 값은 따옴표 없는 키입니다.

## 설정

`.env.example`을 Git에서 제외된 `.env`로 복사합니다. 비밀번호·API Key는 코드와 Git 추적 문서에 저장하지 않습니다.

| 변수 | 역할 |
| --- | --- |
| `MCP_API_KEYS` | HTTP `X-Api-Key`. 로컬 스모크 키. 포털 `dh_`·`tm_po_api_key`가 아님 |
| `MCP_PG_HOST` / `PORT` / `DB` / `USER` / `PASSWORD` | 목록·허용 게이트용 마트 인벤토리. SELECT 실행용이 아님. 없으면 카탈로그 postgres 소스만 빠지고 기동은 유지 |
| `ROBO_META_URL` | `POST /meta/catalog`와 `POST /query_execute` 공통. 기본 `http://robo-meta-api:8100` |
| `MCP_ROW_LIMIT` | 행 상한. env 값을 그대로 씀 |
| `MCP_TB_HOST` / `PORT` / `SID` / `USER` / `PASSWORD` | 수집 Tibero 인벤토리 thin(`host:port:SID`). 비밀번호는 `.env`에만 |
| `MCP_TB_JDBC_JAR` | 목록용 JDBC JAR. compose 기본 `/opt/tibero/jdbc/tibero7-jdbc.jar`. 호스트 파일은 `driver/tibero-jdbc.jar` |

접속 정본은 OA에서 `SourceDbConn`입니다. 로컬은 env/CLI입니다.

## 테스트

```powershell
python -m pytest tests -q
```

## 알려진 이슈·한계

| 항목 | 설명 | 상태 |
| --- | --- | --- |
| **Tibero 실행** | 행 조회는 `/query_execute`. 목록에 나오려면 `MCP_TB_*` 인벤토리 | JDBC 접속이 없으면 Tibero 표는 목록에서 빠짐 |
| **포털 키·감사** | `tm_po_api_key` / `th_po_api_call` / 등급·활용신청 | 미구현. 로컬 키는 폐기 대상 |
| **자유 SQL** | Gemini 피드백의 `execute_read_only_sql` | 넣지 않음 |
| **행 상한 1000** | Gemini 피드백 | 하드캡 200 해제. `MCP_ROW_LIMIT`를 따름 |

## 관련

데이터허브 조회 셋: 플랫폼(메타 적재·Serving) → `robo-meta-api`(카탈로그·실행 API) → 이 MCP(에이전트 도구).
메타스토어 DSN·MindsDB 접속은 MCP에 없다. `ROBO_META_URL`(`http://robo-meta-api:8100`)만 본다.

- `robo-meta-api` — `POST /meta/catalog`, `POST /query_execute`
- `K-AIR-metadata-platform` — Serving `t2s_*`
- `K-AIR-Portal` — 이후 정본 창구 `POST /api/v1/mcp`, 키 원장
