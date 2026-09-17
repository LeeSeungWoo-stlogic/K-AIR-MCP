# Tibero JDBC 드라이버 (선택)

`query_table_tibero` / `aggregate_table_tibero` / `join_tables`의 `via=tibero`만 이 JAR을 쓴다.

- 파일 이름: `driver/tibero-jdbc.jar`
- Docker 이미지는 빌드 때 `driver/` 디렉터리를 통째로 `/opt/tibero/jdbc/`에 복사한다.
  JAR이 있으면 `/opt/tibero/jdbc/tibero-jdbc.jar`(= `TIBERO_JDBC_JAR`)가 된다.
- **JAR이 없어도 빌드는 된다.** 이 README가 디렉터리를 채운다. 그 경우 Tibero 도구는
  `Tibero JDBC 드라이버 미탑재` 오류를 돌려주고, MindsDB·PG 도구는 그대로 동작한다.
- 라이선스 JAR이라 Git에는 올리지 않는다(`.gitignore`). 클론한 뒤 벤더 JAR을 이 이름으로 두고 빌드한다.
- 이미지를 다시 빌드하지 않고 넣으려면 JAR을 볼륨으로 마운트하고 `TIBERO_JDBC_JAR`에 그 경로를 준다.
- 원본 위치 예: `K-AIR-metadata-platform/driver/tibero-jdbc.jar`
