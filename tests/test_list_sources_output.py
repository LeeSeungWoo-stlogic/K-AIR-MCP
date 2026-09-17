import asyncio
import json

from app import tools
from app.credentials import CredentialStore
from app.settings import Settings
from app.sources_client import SourceEndpoint

_ENDPOINT = SourceEndpoint(
    source_id="RWIS",
    source_name="RWIS",
    engine="postgres",
    host="10.20.30.40",
    port=15432,
    database="rwis_prod_db",
    schema_name="rwis",
    schema_scope=("rwis",),
    enabled=True,
    username="ds_account_name",
)


def _settings() -> Settings:
    return Settings(
        api_keys=("x",),
        stone_meta_url="http://stone-meta-api:8096",
        robo_meta_url="http://stone-meta-api:8096",
        nk_backend_url="http://nk-backend:8000",
        nk_backend_token="",
    )


def _patch(monkeypatch):
    async def fake_endpoints(_settings):
        return [_ENDPOINT]

    async def fake_catalog(_settings):
        return {
            "sources": [
                {
                    "source_name": "RWIS",
                    "engine": "postgres",
                    "tables": [{"schema_name": "rwis", "table_name": "t1", "columns": []}],
                }
            ]
        }

    monkeypatch.setattr(tools, "load_endpoints", fake_endpoints)
    monkeypatch.setattr(tools, "load_catalog", fake_catalog)


def _assert_no_coordinates(payload: dict):
    text = json.dumps(payload, ensure_ascii=False)
    for secret in ("10.20.30.40", "15432", "rwis_prod_db", "ds_account_name", "pw-secret"):
        assert secret not in text, secret


def test_list_sources_hides_host_port_db_username(monkeypatch):
    _patch(monkeypatch)
    store = CredentialStore().scoped("key:a")
    out = asyncio.run(tools.list_sources(_settings(), store))
    item = out["items"][0]
    assert set(item) == {
        "source_name",
        "engine",
        "schema_name",
        "table_count",
        "datasource_registered",
        "enabled",
        "credentials_set",
        "credentials_origin",
    }
    assert item["credentials_set"] is False
    _assert_no_coordinates(out)


def test_set_credentials_result_hides_coordinates_and_password(monkeypatch):
    _patch(monkeypatch)
    store = CredentialStore().scoped("key:a")
    out = asyncio.run(tools.set_credentials(_settings(), store, "RWIS", "alice", "pw-secret"))
    _assert_no_coordinates(out)
    listed = asyncio.run(tools.list_sources(_settings(), store))
    assert listed["items"][0]["credentials_origin"] == "caller"
