"""PG·Tibero 직조회가 함께 쓰는 동시 실행 한도.

한 원천이 멈춰도 직조회 슬롯만 막히고 MindsDB·카탈로그 도구는 계속 돈다.
세마포어는 이벤트 루프마다 따로 둔다(테스트가 asyncio.run 을 여러 번 부른다).
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator


class DirectBusyError(RuntimeError):
    pass


_slots: dict[tuple[int, int], asyncio.Semaphore] = {}


def _semaphore(max_concurrency: int) -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    size = max(1, int(max_concurrency))
    key = (id(loop), size)
    sem = _slots.get(key)
    if sem is None:
        # 닫힌 루프의 세마포어가 쌓이지 않게 다른 루프 항목은 버린다.
        for stale in [k for k in _slots if k[0] != id(loop)]:
            _slots.pop(stale, None)
        sem = asyncio.Semaphore(size)
        _slots[key] = sem
    return sem


@asynccontextmanager
async def direct_slot(max_concurrency: int, *, wait_s: float) -> AsyncIterator[None]:
    sem = _semaphore(max_concurrency)
    try:
        await asyncio.wait_for(sem.acquire(), timeout=max(0.001, float(wait_s)))
    except (asyncio.TimeoutError, TimeoutError) as exc:
        raise DirectBusyError(
            f"직조회 동시 실행 한도({max(1, int(max_concurrency))})가 찼습니다. 잠시 뒤 다시 시도하세요."
        ) from exc
    try:
        yield
    finally:
        sem.release()
