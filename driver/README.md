# Tibero JDBC driver placement

K-water/Tibero 운영 기본 경로입니다. 이 디렉터리에 **라이선스가 있는** Tibero JDBC
JAR을 `tibero-jdbc.jar` 이름으로 배치합니다.

```text
<deployment-root>/
  driver/
    tibero-jdbc.jar   # vendor file (not in Git)
  docker-compose.yml
  .env
```

- Git/image에 JAR을 포함하지 않습니다.
- `docker compose up`은 `./driver/tibero-jdbc.jar`를 `kair-mcp-query`의
  `/opt/tibero/jdbc/tibero7-jdbc.jar`에 read-only bind mount합니다.
- `.env`의 `MCP_TB_JDBC_JAR`는 컨테이너 경로
  `/opt/tibero/jdbc/tibero7-jdbc.jar`를 가리킵니다.
- 파일이 없으면 compose bind mount가 실패합니다.

접속값(`MCP_TB_HOST` · `PORT` · `SID` · `USER` · `PASSWORD`)은 Git에 없는
`.env`에만 둡니다. 원천 비밀번호는 메타데이터 스토어 암호문을 복사하지 않습니다.
