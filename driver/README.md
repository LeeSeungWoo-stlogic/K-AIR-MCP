# Tibero JDBC 드라이버 (필수)

`query_table_tibero` / `aggregate_table_tibero` / `join_tables`의 `via=tibero`는 이 JAR이 있어야 한다.

- 파일 이름: `driver/tibero-jdbc.jar`
- Docker 이미지는 빌드 때 이 파일을 넣는다 (`Dockerfile` → `/opt/tibero/jdbc/tibero-jdbc.jar`).
- Git에는 올리지 않는다 (`.gitignore`). 클론한 뒤 벤더 JAR을 이 이름으로 두면 된다.
- 원본 위치 예: `K-AIR-metadata-platform/driver/tibero-jdbc.jar`
