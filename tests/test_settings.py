from app.settings import Settings


def _settings(**overrides) -> Settings:
    values = dict(
        api_keys=("k",),
        pg_host="host.docker.internal",
        pg_port=5434,
        pg_db="",
        pg_user="",
        pg_password="",
        robo_meta_url="http://robo-meta-api:8100",
        row_limit=200,
        api_host="0.0.0.0",
        api_port=8110,
        tb_host="192.168.0.68",
        tb_port=28629,
        tb_sid="tibero",
        tb_user="sys",
        tb_password="x",
        tb_jdbc_jar="/opt/tibero/jdbc/tibero7-jdbc.jar",
    )
    values.update(overrides)
    return Settings(**values)


def test_postgres_is_optional_when_tibero_is_set():
    settings = _settings()
    assert settings.pg_configured is False
    assert settings.tb_configured is True


def test_postgres_configured_requires_db_user_password():
    settings = _settings(pg_db="rwis", pg_user="postgres", pg_password="p")
    assert settings.pg_configured is True
