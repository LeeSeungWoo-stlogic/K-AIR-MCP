import asyncio
import sys
import threading
import time
import types

import pytest

from app import direct_limit, tibero_runner
from app.sources_client import SourceEndpoint


def _endpoint() -> SourceEndpoint:
    return SourceEndpoint(
        source_id="HDAPS",
        source_name="HDAPS",
        engine="tibero",
        host="10.0.0.1",
        port=1629,
        database="tibero",
        schema_name="NBEAVER",
        schema_scope=("NBEAVER",),
        enabled=True,
    )


class _FakeJavaStatement:
    def __init__(self, block: threading.Event | None = None):
        self.timeout = None
        self.params: list = []
        self.block = block

    def setQueryTimeout(self, seconds):
        self.timeout = seconds

    def setObject(self, index, value):
        self.params.append((index, value))

    def execute(self):
        if self.block is not None:
            self.block.wait(5)
        return False

    def getUpdateCount(self):
        return -1

    def cancel(self):
        if self.block is not None:
            self.block.set()

    def close(self):
        pass


class _FakeJConn:
    def __init__(self, stmt):
        self.stmt = stmt
        self.read_only = None
        self.auto_commit = None
        self.rolled_back = 0

    def prepareStatement(self, sql):
        self.sql = sql
        return self.stmt

    def setReadOnly(self, flag):
        self.read_only = flag

    def setAutoCommit(self, flag):
        self.auto_commit = flag

    def rollback(self):
        self.rolled_back += 1


class _FakeCursor:
    def __init__(self, connection):
        self._connection = connection
        self._prep = None
        self._rs = None
        self._meta = None
        self.description = [("A",)]
        self.rowcount = 0

    def _close_last(self):
        self._prep = None

    def _set_stmt_parms(self, prep, params):
        for i, value in enumerate(params):
            prep.setObject(i + 1, value)

    def fetchmany(self, n):
        return []

    def close(self):
        pass


class _FakeConnection:
    def __init__(self, stmt):
        self.jconn = _FakeJConn(stmt)
        self.closed = 0

    def cursor(self):
        return _FakeCursor(self)

    def close(self):
        self.closed += 1


def test_execute_sets_query_timeout_before_execute():
    stmt = _FakeJavaStatement()
    conn = _FakeConnection(stmt)
    handle = tibero_runner._Handle()
    cursor = conn.cursor()
    tibero_runner._execute_with_timeout(cursor, "SELECT 1 FROM DUAL WHERE A = ?", ("x",), 7, handle)
    assert stmt.timeout == 7
    assert stmt.params == [(1, "x")]
    assert handle.statement is stmt
    assert cursor._prep is stmt


def test_fetch_all_times_out_and_aborts(monkeypatch, tmp_path):
    jar = tmp_path / "tibero-jdbc.jar"
    jar.write_bytes(b"")
    release = threading.Event()
    stmt = _FakeJavaStatement(block=release)
    conn = _FakeConnection(stmt)
    monkeypatch.setitem(sys.modules, "jaydebeapi", types.SimpleNamespace(connect=lambda *a, **k: conn))
    monkeypatch.setattr(tibero_runner, "LOGIN_TIMEOUT_S", 0)

    async def run():
        # 문장 한도 1ms → 올림 1s. 바깥 wait_for 가 1s 에 끊어야 한다.
        return await tibero_runner.fetch_all(
            _endpoint(),
            user="u",
            password="p",
            sql="SELECT 1 FROM DUAL",
            max_rows=5,
            jar_path=str(jar),
            statement_timeout_ms=1,
        )

    started = time.monotonic()
    with pytest.raises(tibero_runner.QueryRunError) as info:
        asyncio.run(run())
    assert time.monotonic() - started < 4
    assert "시간 한도" in str(info.value)
    assert release.wait(3), "abort must cancel the running statement"
    deadline = time.monotonic() + 3
    while conn.closed == 0 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert conn.closed >= 1


def test_direct_slot_bounds_concurrency():
    async def run():
        active = 0
        peak = 0

        async def job():
            nonlocal active, peak
            async with direct_limit.direct_slot(2, wait_s=5):
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0.02)
                active -= 1

        await asyncio.gather(*(job() for _ in range(6)))
        return peak

    assert asyncio.run(run()) == 2


def test_direct_slot_busy_error_when_wait_exceeded():
    async def run():
        async with direct_limit.direct_slot(1, wait_s=5):
            with pytest.raises(direct_limit.DirectBusyError):
                async with direct_limit.direct_slot(1, wait_s=0.05):
                    pass

    asyncio.run(run())


def test_settings_reads_direct_max_concurrency(monkeypatch):
    from app.settings import SettingsError, load_settings

    monkeypatch.setenv("MCP_API_KEYS", "k")
    monkeypatch.setenv("MCP_DIRECT_MAX_CONCURRENCY", "2")
    assert load_settings().direct_max_concurrency == 2
    monkeypatch.setenv("MCP_DIRECT_MAX_CONCURRENCY", "0")
    with pytest.raises(SettingsError):
        load_settings()
