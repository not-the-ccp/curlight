import asyncio
import time

import pytest

from curlight import AsyncSession, Timeout


async def test_concurrent_requests(base_url):
    async with AsyncSession() as session:
        start = time.monotonic()
        responses = await asyncio.gather(
            *(session.get(base_url + "/delay?seconds=0.2") for _ in range(5))
        )
        assert all(r.ok for r in responses)
        assert time.monotonic() - start < 0.9
        assert len({r.json()["port"] for r in responses}) == 5


async def test_cookies_and_redirects(base_url):
    async with AsyncSession(headers={"X-Test": "async"}) as session:
        await session.get(base_url + "/cookies")
        response = await session.post(base_url + "/redirect?status=307", json={"a": 1})
        assert response.json()["headers"]["X-Test"] == "async"
        assert "one=1" in response.json()["headers"]["Cookie"]
        assert response.json()["body"] == '{"a":1}'
        assert len(response.history) == 1


async def test_cancel_and_reuse(base_url):
    async with AsyncSession(max_connections=1) as session:
        task = asyncio.create_task(session.get(base_url + "/delay?seconds=1"))
        await asyncio.sleep(0.03)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (await session.get(base_url)).ok
        with pytest.raises(Timeout):
            await session.get(base_url + "/delay", timeout=0.01)
        assert (await session.get(base_url)).ok


async def test_close_cancels_active_and_queued(base_url):
    session = AsyncSession(max_connections=1)
    tasks = [asyncio.create_task(session.get(base_url + "/delay?seconds=1")) for _ in range(3)]
    await asyncio.sleep(0.03)
    await session.aclose()
    assert all(t.cancelled() for t in tasks)
    await session.aclose()
    with pytest.raises(RuntimeError, match="closed"):
        await session.get(base_url)


async def test_callback_exception(base_url):
    def fail(data):
        raise LookupError("sink failed")

    async with AsyncSession() as session:
        with pytest.raises(LookupError, match="sink failed"):
            await session.get(base_url, sink=fail)
        assert (await session.get(base_url)).ok
