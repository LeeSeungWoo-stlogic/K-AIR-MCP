import asyncio
import re
from pathlib import Path

import pytest

from app import tibero_runner, tools
from app.settings import Settings

ROOT = Path(__file__).resolve().parent.parent


def test_missing_jar_is_clear_error(tmp_path):
    with pytest.raises(tibero_runner.QueryRunError) as info:
        tibero_runner.jdbc_jar_path(str(tmp_path / "nope.jar"))
    assert "Tibero JDBC 드라이버 미탑재" in str(info.value)


def test_tibero_tool_reports_missing_driver_before_datasources(monkeypatch, tmp_path):
    settings = Settings(
        api_keys=("x",),
        stone_meta_url="http://stone-meta-api:8096",
        robo_meta_url="http://stone-meta-api:8096",
        nk_backend_url="http://nk-backend:8000",
        nk_backend_token="",
        tibero_jdbc_jar=str(tmp_path / "missing.jar"),
    )

    async def fake_catalog(_url):
        return {
            "sources": [
                {
                    "source_name": "HDAPS",
                    "engine": "tibero",
                    "tables": [{"schema_name": "NBEAVER", "table_name": "DAMCD", "columns": [{"column_name": "DAMCD"}]}],
                }
            ]
        }

    async def no_endpoints(_settings):
        raise AssertionError("must not load datasources when driver is missing")

    monkeypatch.setattr(tools.catalog_client, "fetch_catalog", fake_catalog)
    monkeypatch.setattr(tools, "load_endpoints", no_endpoints)
    with pytest.raises(tools.QueryError) as info:
        asyncio.run(
            tools.query_table_tibero(
                settings, None, {"source_name": "HDAPS", "schema_name": "NBEAVER", "table_name": "DAMCD"}
            )
        )
    assert "미탑재" in str(info.value)


def test_dockerfile_does_not_require_jar_and_pins_base():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY driver/tibero-jdbc.jar" not in text
    assert "COPY driver/ /opt/tibero/jdbc/" in text
    assert re.search(r"^FROM python:3\.11\.\d+-slim$", text, re.M)
    assert (ROOT / "driver" / "README.md").is_file()


def test_requirements_are_exact_pins():
    lines = [
        line.strip()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert lines
    assert all(re.fullmatch(r"[A-Za-z0-9_.\-\[\]]+==[0-9][0-9A-Za-z.]*", line) for line in lines), lines
