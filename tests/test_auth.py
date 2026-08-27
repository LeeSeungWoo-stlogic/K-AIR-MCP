from app.auth import key_ok


def test_key_whitelist():
    assert key_ok("local_mcp_smoke", ("local_mcp_smoke",))
    assert not key_ok("wrong", ("local_mcp_smoke",))
    assert not key_ok("", ("local_mcp_smoke",))
