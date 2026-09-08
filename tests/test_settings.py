from app.settings import Settings


def test_settings_has_no_physical_db_fields():
    settings = Settings(
        api_keys=("k",),
        robo_meta_url="http://robo-meta-api:8100",
        row_limit=200,
        api_host="0.0.0.0",
        api_port=8110,
    )
    assert settings.robo_meta_url == "http://robo-meta-api:8100"
    assert not hasattr(settings, "pg_configured")
    assert not hasattr(settings, "tb_configured")
    assert not hasattr(settings, "pg_conninfo")
