from app.credentials import CredentialStore, credentials_from_environ


def test_credentials_from_environ_needs_both_user_and_password():
    loaded = credentials_from_environ(
        {
            "MCP_DS_USER_RWIS": "rwis_readonly",
            "MCP_DS_PASSWORD_RWIS": "secret",
            "MCP_DS_USER_OTHER": "only-user",
        }
    )
    assert set(loaded) == {"rwis"}
    assert loaded["rwis"].user == "rwis_readonly"
    assert loaded["rwis"].password == "secret"


def test_load_environ_seeds_store():
    store = CredentialStore()
    names = store.load_environ(
        {
            "MCP_DS_USER_RWIS": "rwis_readonly",
            "MCP_DS_PASSWORD_RWIS": "secret",
        }
    )
    assert names == ("rwis",)
    assert store.has("RWIS")
    login = store.get("RWIS")
    assert login is not None
    assert login.user == "rwis_readonly"
