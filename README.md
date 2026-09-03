# K-AIR MCP

에이전트가 데이터허브 **조회**만 하도록 여는 공식 MCP 서버입니다. 카탈로그 서빙 및 질의 실행은 `robo-meta-api`와 연계하여 동작하며, 특정 물리 DB에 종속되지 않습니다. SQL 문자열은 직접 받지 않습니다.

도구 인자로 SELECT를 조립한 뒤 `robo-meta-api` `POST /query_execute`로 실행합니다. 에이전트에 자유 SQL 문자열 도구는 없습니다.

**업데이트 이력:** [`change_log.md`](change_log.md)

## 이 서비스가 하는 일

- 에이전트에 표 목록·컬럼 상세·고유값·제한 SELECT·집계 도구를 줍니다.
- 허용 표 = `POST /meta/catalog`에 등록된 표·컬럼 (단일 진실 공급원).
- HTTP는 Streamable HTTP(`/mcp`) + `X-Api-Key`. stdio는 같은 PC IDE용입니다.
- AI는 MCP URL과 API Key만 압니다. DB 비밀번호는 필요하지 않으며 도구 결과에도 없습니다.

하지 않는 일: 자유 SQL, DML/DDL, dump/보내기, `t2s`·`argus_catalog` 데이터 조회, 특정 물리 DB 직접 커넥션 요구.

## 도구

| 도구 | 역할 |
| --- | --- |
| `list_tables` | 허용 표 목록. 선택 `schema_name`. 응답에 `engine` |
| `describe_table` | 컬럼 타입·PK·코멘트. 카탈로그 메타데이터 서빙 |
| `get_distinct_values` | 허용 컬럼 DISTINCT. 상한은 `MCP_ROW_LIMIT` |
| `query_table` | 조립 SELECT. `columns`, `filters` `{column,op,value}`, `order_by` `{column,dir}` |
| `aggregate_table` | `count`/`sum`/`avg`/`max`/`min`. 선택 `filters` `{column,op,value}`. 전체 행 수는 `func=count` 그리고 column 없음 |

행 상한은 `MCP_ROW_LIMIT`(기본 200). 실행 SELECT는 `POST /query_execute`. `filters.op`: eq, ne, gt, gte, lt, lte, like, in, is_null, is_not_null.

## 데이터소스 구분

`/meta/catalog`의 `sources[].engine`이 정본입니다. 에이전트가 엔진을 고르지 않습니다. 플랫폼에 등록된 Postgres, Tibero 등 모든 데이터소스가 카탈로그를 통해 균일하게 서빙됩니다.

허용 표는 카탈로그에 등록된 표·컬럼입니다. MCP가 물리 DB에 직접 붙어 실존 여부를 재확인하지 않습니다. 실행은 `robo-meta-api` `POST /query_execute`입니다.

## 구성

```text
app/                 FastMCP 서버 (stdio / Streamable HTTP)
tests/               단위·계약 테스트
docker-compose.yml   네트워크용 http :8110
mcp.cursor.example.json       같은 PC stdio
mcp.cursor.http.example.json  다른 PC HTTP
```

전제: `robo-meta-api`와 `kair-metadata-platform_control-plane` 네트워크. 필수 설정은 `MCP_API_KEYS`와 `ROBO_META_URL`. 포털·OASIS는 이 저장소 범위가 아닙니다.

## 실행

```powershell
copy .env.example .env
# MCP_API_KEYS 필수. 따옴표 넣지 않음
docker compose up -d --build
curl.exe -fsS http://127.0.0.1:8110/health
```

헬스 본문은 `backend=robo-meta-api`입니다. 물리 엔진 목록을 넣지 않습니다.

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
| `ROBO_META_URL` | `POST /meta/catalog`와 `POST /query_execute` 공통. 기본 `http://robo-meta-api:8100` |
| `MCP_ROW_LIMIT` | 행 상한. env 값을 그대로 씀 |
| `API_HOST` / `API_PORT` | HTTP 바인드. 기본 `0.0.0.0:8110` |

접속 정본은 플랫폼 Serving과 `robo-meta-api`입니다. MCP에 DB 비밀번호를 넣지 않습니다.

## 테스트

```powershell
python -m pytest tests -q
```

## 알려진 이슈·한계

| 항목 | 설명 | 상태 |
| --- | --- | --- |
| **실행면** | 행·집계·고유값은 `/query_execute` | 카탈로그에 있는 표만 조립 SELECT |
| **포털 키·감사** | `tm_po_api_key` / `th_po_api_call` / 등급·활용신청 | 미구현. 로컬 키는 폐기 대상 |
| **자유 SQL** | Gemini 피드백의 `execute_read_only_sql` | 넣지 않음 |
| **행 상한 1000** | Gemini 피드백 | 하드캡 200 해제. `MCP_ROW_LIMIT`를 따름 |

## 관련

데이터허브 조회 셋: 플랫폼(메타 적재·Serving) → `robo-meta-api`(카탈로그·실행 API) → 이 MCP(에이전트 도구).
메타스토어 DSN·MindsDB 접속은 MCP에 없다. `ROBO_META_URL`(`http://robo-meta-api:8100`)만 본다.

- `robo-meta-api` — `POST /meta/catalog`, `POST /query_execute`
- `K-AIR-metadata-platform` — Serving `t2s_*`
- `K-AIR-Portal` — 이후 정본 창구 `POST /api/v1/mcp`, 키 원장
