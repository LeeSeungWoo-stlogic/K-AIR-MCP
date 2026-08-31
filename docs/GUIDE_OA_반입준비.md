# OA 반입 준비 — K-AIR-MCP

**작성:** 2026-08-27  
**전제:** `robo-meta-api`와 **같은 환경**(VM 163, `robo-network`, keep `postgres_analysis`).  
**근거:** 260825 platform/robo 반입 절차, 본 저장소 README·`docker-compose.yml`·Dockerfile, `K-water_docs/REPORT_260826_연계서버_MCP_APIKey_조회서비스.md`.  
**절차 정본(플랫폼·robo):** `K_Water_v1/oa_work/docker_part/docs/GUIDE_OA_반입절차_platform_robo.md`  
**시크릿·접속 문자열은 이 문서에 적지 않는다.**

아직 패키지·이미지는 없다. 이 문서는 **반입본을 만들기 전에 고정할 것**이다. 원본 `K-AIR-MCP` git에 OA 암호를 커밋하지 않는다.

---

## 0. 한 줄

MCP는 robo에 합치지 않는다. 163에서 http `:8110`으로 붙고, 카탈로그는 **같은 Docker 망의 robo** `POST /meta/catalog`, 마트 SELECT는 **keep `postgres_analysis`(호스트 5434)** 이다. 새 bridge를 만들지 않는다.

---

## 1. 역할 (로컬 README와 동일)

- 도구로 SELECT를 조립한다. 자유 SQL·DML/DDL·dump 없음.
- 허용 표 = robo `POST /meta/catalog` ∩ 해당 엔진 원천에 있는 표.
- HTTP: Streamable HTTP `/mcp` + `X-Api-Key`. AI는 URL과 키만 안다.
- 로컬 compose 기본 이미지 `kair-mcp-query:dev`, 포트 8110, 컨테이너명 `kair-mcp-query`.

하지 않음: 포털 `POST /mcp` 목업 복제, 엔진마다 MCP 분리, `t2s`/`argus_catalog` 데이터 조회, 운영 Tibero SID.

포털 키 원장(`tm_po_api_key`)·감사는 1단계 OA 반입에 넣지 않는다. OA 키는 현장 기입 스모크 키. 폐기 대상인 점은 연계서버 문서와 같다.

---

## 2. 로컬 compose와 OA가 다른 점

로컬 `docker-compose.yml`:

| 로컬 | OA에서 |
|------|--------|
| 망 `kair-metadata-platform_control-plane` | **`robo-network` external** (robo·platform oa overlay와 동일). 새 브리지 금지 |
| `ROBO_META_URL=http://robo-meta-api:8100` | 서비스/컨테이너명은 **`robo-meta-api-v4`**. URL은 `http://robo-meta-api-v4:8100` |
| `MCP_PG_HOST=host.docker.internal` 포트 5434 | keep **`postgres_analysis`**. 컨테이너에서 `host.docker.internal:5434` 또는 같은 망이면 컨테이너명. 호스트 포트 5434는 유지 |
| `image: kair-mcp-query:dev` · `--build` | 일자 태그(예 `:260827`)로 빌드·save·load. `--pull never`. 163에서 빌드하지 않는 것이 825와 같음 |
| 프로젝트명 `kair-mcp-local` | OA 전용 overlay. 기본 브리지 생성 금지 |

robo와 같이 둘 것:

- `extra_hosts`: `host.docker.internal:host-gateway` (필요 시 `aion.kwater.or.kr`)
- `pull_policy: never`
- 스크립트 `bash`. `.env`·`SHA256SUMS` **LF**
- `network prune` 금지. keep 내리지 않음
- 163:80 본선 전환 금지. 152에 `/mcp`를 넣을지는 **미정**. 우선 163 `:8110` listen

Tibero: JDBC JAR는 이미지에 넣지 않는다(README). 수집 접속이 생기면 bind mount + `MCP_TB_*`. 운영 인스턴스 금지.

---

## 3. 반입본 모양 (825 템플릿)

825와 같은 골격으로 만든다. 원본 repo는 커밋하지 않는다.

```text
OA_source/<일자>_kair-mcp/
  images/kair-mcp-query_<일자>.tar.gz
  runtime/           # git archive HEAD + overlay
    docker-compose.oa.yml
    .env             # 현장 기입. Git에 올리지 않음
  scripts/preflight-oa.sh  load-images.sh  up-oa.sh
  SHA256SUMS         # LF
  docs/GUIDE_...     # 이 문서 요약
```

`docker-compose.oa.yml` 초안 (값은 현장이 채움):

```yaml
services:
  kair-mcp-query:
    image: kair-mcp-query:<일자>
    pull_policy: never
    container_name: kair-mcp-query
    restart: unless-stopped
    command: ["--transport", "http"]
    ports:
      - "8110:8110"
    env_file:
      - .env
    environment:
      API_HOST: "0.0.0.0"
      API_PORT: "8110"
      ROBO_META_URL: "${ROBO_META_URL:-http://robo-meta-api-v4:8100}"
    extra_hosts:
      - "host.docker.internal:host-gateway"
    networks:
      - oa-net

networks:
  oa-net:
    name: ${KAIR_OA_NETWORK:-robo-network}
    external: true
```

기동 전제: `robo-meta-api-v4`가 같은 망에 있고 `/health`가 된다. MCP만 먼저 올리면 카탈로그가 비거나 실패한다.

---

## 4. `.env` (이름만. 값은 163에서)

| 변수 | OA |
|------|-----|
| `MCP_API_KEYS` | 현장 스모크 키. 포털 `dh_` 아님 |
| `ROBO_META_URL` | `http://robo-meta-api-v4:8100` |
| `MCP_PG_HOST` / `PORT` / `DB` / `USER` / `PASSWORD` | 마트 SELECT. 포트 기본 5434(`postgres_analysis`). DB/계정은 현장 |
| `MCP_ROW_LIMIT` | env 값을 그대로 씀. 기본 예시는 200 |
| `MCP_TB_*` | 수집 접속·JAR가 있을 때만 |

로컬 `.env`의 비밀번호를 패키지에 복사하지 않는다.

---

## 5. 163 절차 (패키지가 생긴 뒤)

platform/robo와 같은 습관.

```bash
bash scripts/preflight-oa.sh    # robo-network, keep, 172.20 거절
bash scripts/load-images.sh     # SHA256SUMS LF
# .env 기입 후
bash scripts/up-oa.sh
curl -fsS http://127.0.0.1:8110/health
```

헬스 예: `server`=`kair-mcp-query`, `transport`=`streamable-http`. `engines`에 postgres가 보여야 마트 접속이 된 것.

```bash
docker inspect kair-mcp-query --format '{{.Config.Image}}'
docker network inspect robo-network --format '{{range .Containers}}{{.Name}} {{end}}'
```

`kair-mcp-query`와 `robo-meta-api-v4`가 같은 망에 있어야 한다.

152에 경로를 열 때: `datahub-relay`는 `nginx -t` + `-s reload`만. 새 location은 `/robo/`·`/meta/`를 덮지 않게 쓴다. 지금 단계에서는 **163:8110 직접 확인**이 본선.

---

## 6. 하지 말 것

- MCP를 `robo-meta-api` 이미지/프로세스에 합치기
- 로컬 망 이름 그대로 163에 `docker network create`
- `postgres_analysis` / `kair-graphdb` `down -v`
- 운영 Tibero, `argus_catalog` 조회
- 자유 SQL 도구 (`execute_read_only_sql`)
- 행 상한은 `MCP_ROW_LIMIT`. 서버 하드캡 200은 해제됨
- 원본 repo에 OA `.env` 커밋
- `SHA256SUMS` CRLF

---

## 7. 반입 전에 남은 결정

1. 이미지 일자 태그
2. 152 `:8000`에 MCP를 올릴지 (올리면 path·upstream만. 163:80 전환 아님)
3. 수집 Tibero를 이번 패키지에 넣을지 (JAR bind + `MCP_TB_*`)
4. 스모크 키 관리자·폐기 시점 (포털 키 연동은 이후)
