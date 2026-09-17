from app.gateway import health_path


def test_health_path_exact():
    assert health_path("/health")
    assert health_path("/health/")


def test_health_path_rejects_mcp_and_lookalikes():
    for path in ("/mcp", "/mcp/", "/", "", "/healthz", "/health/../mcp", "/x/health", "/mcp/health"):
        assert not health_path(path), path


def test_main_imports():
    import app.main  # noqa: F401 - gateway 누락 시 import 에서 죽던 회귀
