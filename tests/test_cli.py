from app.cli import parse_args


def test_default_is_stdio():
    assert parse_args([]).transport == "stdio"


def test_http_flag():
    assert parse_args(["--transport", "http"]).transport == "http"


def test_stdio_flag():
    assert parse_args(["--transport", "stdio"]).transport == "stdio"
