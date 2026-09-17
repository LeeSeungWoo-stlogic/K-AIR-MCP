from __future__ import annotations

import asyncio
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from .sources_client import SourceEndpoint

TIBERO_DRIVER_CLASS = "com.tmax.tibero.jdbc.TbDriver"
DEFAULT_JAR = "/opt/tibero/jdbc/tibero-jdbc.jar"
_SAFE_HOST = re.compile(r"^[A-Za-z0-9._:-]+$")
_SAFE_SID = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]*$")
LOGIN_TIMEOUT_S = 10


class QueryRunError(RuntimeError):
    pass


def jdbc_url(endpoint: SourceEndpoint) -> str:
    host = (endpoint.host or "").strip()
    if not _SAFE_HOST.fullmatch(host) or any(ch in host for ch in "@/;"):
        raise QueryRunError(f"Tibero host 가 올바르지 않습니다: {host!r}")
    if endpoint.port < 1 or endpoint.port > 65535:
        raise QueryRunError("Tibero port 가 올바르지 않습니다.")
    sid = (endpoint.database or "").strip()
    if not _SAFE_SID.fullmatch(sid):
        raise QueryRunError(f"Tibero SID 가 올바르지 않습니다: {sid!r}")
    return f"jdbc:tibero:thin:@{host}:{int(endpoint.port)}:{sid}"


def jdbc_jar_path(explicit: str | None = None) -> str:
    candidate = (explicit or os.environ.get("TIBERO_JDBC_JAR") or DEFAULT_JAR).strip()
    path = Path(candidate)
    if not path.is_file():
        raise QueryRunError(
            f"Tibero JDBC 드라이버 미탑재: {path} 에 JAR 이 없습니다. "
            "이미지 빌드 때 driver/tibero-jdbc.jar 를 두거나 TIBERO_JDBC_JAR 로 마운트 경로를 지정하세요."
        )
    return str(path)


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    return value


class _Handle:
    """작업 스레드가 연 연결·문장. 시간 초과 때 이벤트 루프 쪽에서 끊는다."""

    def __init__(self) -> None:
        self.connection: Any = None
        self.statement: Any = None
        self.abandoned = False
        self.lock = threading.Lock()


def _abort(handle: _Handle) -> None:
    """최선 노력으로 문장 취소·연결 종료. 네트워크가 멈춰도 이벤트 루프를 붙잡지 않게 별도 스레드에서 부른다."""
    with handle.lock:
        handle.abandoned = True
        statement, connection = handle.statement, handle.connection
    if statement is not None:
        try:
            statement.cancel()
        except Exception:
            pass
    if connection is not None:
        try:
            connection.close()
        except Exception:
            pass


def _set_login_timeout(seconds: int) -> None:
    """DriverManager 로그인 한도. JVM 이 떠 있어야 걸 수 있어 첫 연결은 바깥 wait_for 가 막는다."""
    try:
        import jpype

        if jpype.isJVMStarted():
            jpype.java.sql.DriverManager.setLoginTimeout(int(seconds))
    except Exception:
        pass


def _make_read_only(connection: Any) -> None:
    """최선 노력. 드라이버가 readOnly 힌트를 무시해도 autocommit 끄고 끝에 rollback 한다."""
    jconn = getattr(connection, "jconn", None)
    if jconn is None:
        return
    try:
        jconn.setReadOnly(True)
    except Exception:
        pass
    try:
        jconn.setAutoCommit(False)
    except Exception:
        pass


def _rollback_quietly(connection: Any) -> None:
    jconn = getattr(connection, "jconn", None)
    if jconn is None:
        return
    try:
        jconn.rollback()
    except Exception:
        pass


def _execute_with_timeout(cursor: Any, sql: str, params: tuple[Any, ...], timeout_s: int, handle: _Handle) -> None:
    """jaydebeapi Cursor.execute 와 같되, 실행 전에 Statement.setQueryTimeout 을 건다.

    jaydebeapi 1.2.3 은 execute 안에서 PreparedStatement 를 만들고 바로 실행해 한도를 걸 틈이 없다.
    그래서 같은 순서를 여기서 밟고 cursor 내부 칸(_prep/_rs/_meta)을 채워 fetchmany 를 그대로 쓴다.
    """
    cursor._close_last()
    prep = cursor._connection.jconn.prepareStatement(sql)
    cursor._prep = prep
    with handle.lock:
        handle.statement = prep
    prep.setQueryTimeout(max(1, int(timeout_s)))
    cursor._set_stmt_parms(prep, params or ())
    if prep.execute():
        cursor._rs = prep.getResultSet()
        cursor._meta = cursor._rs.getMetaData()
        cursor.rowcount = -1
    else:
        cursor.rowcount = prep.getUpdateCount()


def _fetch_sync(
    endpoint: SourceEndpoint,
    *,
    user: str,
    password: str,
    sql: str,
    params: tuple[Any, ...],
    max_rows: int,
    jar_path: str,
    timeout_s: int = 60,
    handle: _Handle | None = None,
) -> list[dict[str, Any]]:
    try:
        import jaydebeapi
    except ImportError as exc:
        raise QueryRunError("JayDeBeApi 가 필요합니다. Tibero JDBC 직조회용입니다.") from exc
    handle = handle or _Handle()
    connection = None
    cursor = None
    try:
        _set_login_timeout(LOGIN_TIMEOUT_S)
        connection = jaydebeapi.connect(
            TIBERO_DRIVER_CLASS,
            jdbc_url(endpoint),
            [user, password],
            jar_path,
        )
        with handle.lock:
            handle.connection = connection
            abandoned = handle.abandoned
        if abandoned:
            raise QueryRunError("원천 Tibero 조회가 시간 초과로 취소되었습니다.")
        _make_read_only(connection)
        cursor = connection.cursor()
        _execute_with_timeout(cursor, sql, params, timeout_s, handle)
        description = cursor.description or []
        names = [str(col[0]) for col in description]
        rows: list[dict[str, Any]] = []
        cap = max(1, int(max_rows))
        for raw in cursor.fetchmany(cap) or []:
            if isinstance(raw, dict):
                rows.append({str(key): _jsonable(value) for key, value in raw.items()})
                continue
            values = list(raw)
            rows.append({names[i]: _jsonable(values[i]) for i in range(min(len(names), len(values)))})
        return rows
    except QueryRunError:
        raise
    except Exception as exc:  # noqa: BLE001 - JDBC 예외 종류가 드라이버마다 다름
        raise QueryRunError(f"원천 Tibero 조회에 실패했습니다: {exc}") from exc
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        if connection is not None:
            _rollback_quietly(connection)
            try:
                connection.close()
            except Exception:
                pass


_executor: ThreadPoolExecutor | None = None
_executor_size = 0


def _tibero_executor(size: int) -> ThreadPoolExecutor:
    """Tibero 전용 스레드 풀. 멈춘 JDBC 호출이 기본 풀(to_thread)을 잠식하지 않게 한다."""
    global _executor, _executor_size
    size = max(1, int(size))
    if _executor is None or _executor_size != size:
        _executor = ThreadPoolExecutor(max_workers=size, thread_name_prefix="tibero-jdbc")
        _executor_size = size
    return _executor


async def fetch_all(
    endpoint: SourceEndpoint,
    *,
    user: str,
    password: str,
    sql: str,
    params: tuple[Any, ...] = (),
    max_rows: int,
    jar_path: str | None = None,
    statement_timeout_ms: int = 60000,
    max_concurrency: int = 4,
) -> list[dict[str, Any]]:
    resolved = jdbc_jar_path(jar_path)
    timeout_s = max(1, -(-int(statement_timeout_ms) // 1000))
    handle = _Handle()
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(
        _tibero_executor(max_concurrency),
        lambda: _fetch_sync(
            endpoint,
            user=user,
            password=password,
            sql=sql,
            params=params,
            max_rows=max_rows,
            jar_path=resolved,
            timeout_s=timeout_s,
            handle=handle,
        ),
    )
    # JDBC 한도(로그인 + 문장)가 먼저 걸리게 두고, 드라이버가 무시해도 여기서 끊는다.
    try:
        return await asyncio.wait_for(future, timeout=timeout_s + LOGIN_TIMEOUT_S)
    except (asyncio.TimeoutError, TimeoutError) as exc:
        threading.Thread(target=_abort, args=(handle,), name="tibero-abort", daemon=True).start()
        raise QueryRunError(
            f"원천 Tibero 조회가 시간 한도({timeout_s + LOGIN_TIMEOUT_S}s)를 넘어 끊었습니다. "
            "MCP_STATEMENT_TIMEOUT_MS 를 확인하세요."
        ) from exc
