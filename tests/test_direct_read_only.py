import asyncio
import sys
import types
from contextlib import asynccontextmanager

from app import pg_runner, tibero_runner
from app.sources_client import SourceEndpoint

from tests.test_direct_timeout import _FakeConnection, _FakeJavaStatement


def _endpoint(engine: str) -> SourceEndpoint:
    return SourceEndpoint(
        source_id="S",
        source_name="S",
        engine=engine,
        host="10.0.0.1",
        port=5432 if engine == "postgres" else 1629,
        database="db" if engine == "postgres" else "tibero",
        schema_name="s",
        schema_scope=("s",),
        enabled=True,
    )


class _FakePg:
    def __init__(self):
        self.log: list = []

    async def execute(self, sql):
        self.log.append(("execute", sql))

    def transaction(self, **kwargs):
        log = self.log

        @asynccontextmanager
        async def _tx():
            log.append(("begin", kwargs))
            yield
            log.append(("end", kwargs))

        return _tx()

    async def fetch(self, sql, *params):
        self.log.append(("fetch", sql, params))
        return []

    async def close(self):
        self.log.append(("close",))


def test_pg_runs_select_in_read_only_transaction(monkeypatch):
    fake = _FakePg()

    async def connect(**kwargs):
        return fake

    monkeypatch.setattr(pg_runner.asyncpg, "connect", connect)
    asyncio.run(
        pg_runner.fetch_all(
            _endpoint("postgres"),
            user="u",
            password="p",
            sql="SELECT 1",
            max_rows=5,
            statement_timeout_ms=1234,
        )
    )
    setup = fake.log[0][1]
    assert "statement_timeout = 1234" in setup
    assert "READ ONLY" in setup
    kinds = [entry[0] for entry in fake.log]
    assert kinds == ["execute", "begin", "fetch", "end", "close"]
    assert fake.log[1][1] == {"readonly": True}


def test_tibero_sets_read_only_and_rolls_back(monkeypatch, tmp_path):
    jar = tmp_path / "tibero-jdbc.jar"
    jar.write_bytes(b"")
    conn = _FakeConnection(_FakeJavaStatement())
    monkeypatch.setitem(sys.modules, "jaydebeapi", types.SimpleNamespace(connect=lambda *a, **k: conn))
    rows = asyncio.run(
        tibero_runner.fetch_all(
            _endpoint("tibero"),
            user="u",
            password="p",
            sql="SELECT 1 FROM DUAL",
            max_rows=5,
            jar_path=str(jar),
        )
    )
    assert rows == []
    assert conn.jconn.read_only is True
    assert conn.jconn.auto_commit is False
    assert conn.jconn.rolled_back == 1
    assert conn.closed == 1
