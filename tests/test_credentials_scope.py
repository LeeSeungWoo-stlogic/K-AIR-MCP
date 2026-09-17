import json

import pytest

from app import main, tools
from app.credentials import LOCAL_SCOPE, CredentialStore, DbLogin, scope_for_api_key
from app.runtime import RT
from app.settings import Settings
from app.sources_client import SourceEndpoint


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_caller_scopes_are_isolated():
    store = CredentialStore()
    a = store.scoped(scope_for_api_key("key-a"))
    b = store.scoped(scope_for_api_key("key-b"))
    a.set("RWIS", "alice", "pw-a")
    assert a.get("RWIS").user == "alice"
    assert b.get("RWIS") is None
    assert not b.has("RWIS")


def test_caller_scope_wins_over_env_and_clear_keeps_env():
    store = CredentialStore()
    store.load_environ({"MCP_DS_USER_RWIS": "svc", "MCP_DS_PASSWORD_RWIS": "svc-pw"})
    a = store.scoped(scope_for_api_key("key-a"))
    b = store.scoped(scope_for_api_key("key-b"))
    assert a.get("RWIS").user == "svc"
    assert a.origin("RWIS") == "env"
    a.set("RWIS", "alice", "pw-a")
    assert a.get("RWIS").user == "alice"
    assert a.origin("RWIS") == "caller"
    assert b.get("RWIS").user == "svc"
    a.clear()
    assert a.get("RWIS").user == "svc"


def test_clear_only_touches_caller_scope():
    store = CredentialStore()
    a = store.scoped("key:a")
    b = store.scoped("key:b")
    a.set("RWIS", "alice", "pw")
    b.set("RWIS", "bob", "pw")
    a.clear("RWIS")
    assert a.get("RWIS") is None
    assert b.get("RWIS").user == "bob"


def test_credentials_expire_after_ttl():
    clock = _Clock()
    store = CredentialStore(ttl_s=60, clock=clock)
    store.set("RWIS", "alice", "pw", scope="key:a")
    clock.now += 59
    assert store.get("RWIS", scope="key:a") is not None
    clock.now += 2
    assert store.get("RWIS", scope="key:a") is None


def test_scope_does_not_contain_raw_key_and_repr_hides_password():
    scope = scope_for_api_key("super-secret-key")
    assert "super-secret-key" not in scope
    assert "pw-123" not in repr(DbLogin(user="u", password="pw-123"))


def test_stdio_scope_is_local(monkeypatch):
    monkeypatch.setattr(RT, "transport", "stdio")
    assert main._caller_scope(None) == LOCAL_SCOPE


def test_http_without_request_fails_closed(monkeypatch):
    monkeypatch.setattr(RT, "transport", "http")
    with pytest.raises(tools.QueryError):
        main._caller_scope(None)


# --- Streamable HTTP 끝단: 키 A 가 넣은 계정이 키 B 에 보이지 않는다 ---


def _settings() -> Settings:
    return Settings(
        api_keys=("key-a", "key-b"),
        stone_meta_url="http://stone-meta-api:8096",
        robo_meta_url="http://stone-meta-api:8096",
        nk_backend_url="http://nk-backend:8000",
        nk_backend_token="",
    )


def _call(client, key: str, name: str, arguments: dict, req_id: int) -> dict:
    response = client.post(
        "/mcp",
        headers={
            "x-api-key": key,
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
        },
        content=json.dumps(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        ),
    )
    assert response.status_code == 200, response.text
    text = response.text
    if "data:" in text:
        text = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")][-1]
    message = json.loads(text)
    result = message["result"]
    assert not result.get("isError"), result
    return result.get("structuredContent") or json.loads(result["content"][0]["text"])


def test_http_credentials_are_scoped_per_api_key(monkeypatch):
    from starlette.testclient import TestClient

    endpoint = SourceEndpoint(
        source_id="RWIS",
        source_name="RWIS",
        engine="postgres",
        host="10.0.0.9",
        port=5432,
        database="rwis",
        schema_name="rwis",
        schema_scope=("rwis",),
        enabled=True,
        username="ds_user",
    )

    async def fake_endpoints(_settings):
        return [endpoint]

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
    monkeypatch.setattr(RT, "settings", _settings())
    monkeypatch.setattr(RT, "transport", "http")
    monkeypatch.setattr(RT, "credentials", CredentialStore())

    app = main.mcp.streamable_http_app()
    app.add_middleware(main.ApiKeyMiddleware)
    with TestClient(app) as client:
        out = _call(client, "key-a", "set_credentials", {"source_name": "RWIS", "user": "alice", "password": "pw-a"}, 1)
        assert "pw-a" not in json.dumps(out)
        seen_a = _call(client, "key-a", "list_sources", {}, 2)
        seen_b = _call(client, "key-b", "list_sources", {}, 3)
        assert seen_a["items"][0]["credentials_set"] is True
        assert seen_b["items"][0]["credentials_set"] is False
        _call(client, "key-b", "clear_credentials", {}, 4)
        assert _call(client, "key-a", "list_sources", {}, 5)["items"][0]["credentials_set"] is True
        denied = client.post("/mcp", headers={"x-api-key": "nope"}, content="{}")
        assert denied.status_code == 401
