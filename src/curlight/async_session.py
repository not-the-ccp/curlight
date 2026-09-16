"""Asyncio integration using libcurl multi (no executor threads)."""

from __future__ import annotations

import asyncio
from typing import Any

from ._backend import backend as b
from ._easy import Curl
from .constants import CurlOpt
from .exceptions import CurlError
from .models import Response
from .session import Session


class _SharedSession(Session):
    def __init__(self, share: Any, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._share = share

    def _configure_shared_state(self, curl: Curl) -> None:
        curl._check(b.easy_setopt(curl._handle, int(CurlOpt.SHARE), b.opt_pointer(self._share)))


class AsyncSession:
    """Concurrent transfers through one multi handle on one asyncio event loop.

    Shares cookies and connections across requests. Uses a 10ms cooperative polling
    interval rather than socket callbacks. Native DNS may block with a synchronous
    resolver build of libcurl. Always use ``async with`` or await ``aclose()``.
    """

    def __init__(self, *, max_connections: int = 20, **session_options: Any) -> None:
        if max_connections < 1:
            raise ValueError("max_connections must be positive")
        self._options = session_options
        self._limit = asyncio.Semaphore(max_connections)
        self._multi = b.lib.curl_multi_init()
        self._share = b.lib.curl_share_init()
        if not self._multi or not self._share:
            if self._multi:
                b.lib.curl_multi_cleanup(self._multi)
            if self._share:
                b.lib.curl_share_cleanup(self._share)
            raise MemoryError("libcurl multi/share allocation failed")
        # CURLSHOPT_SHARE=1, CURL_LOCK_DATA_COOKIE=2. All access is on the loop thread.
        code = b.lib.curl_share_setopt(self._share, 1, b.scalar("int", 2))
        if code:
            b.lib.curl_multi_cleanup(self._multi)
            b.lib.curl_share_cleanup(self._share)
            raise CurlError(code, "could not share cookies")
        self._pending: dict[int, tuple[Curl, asyncio.Future[int]]] = {}
        self._tasks: set[asyncio.Task[Any]] = set()
        self._pump_task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closed = False

    def _check_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._closed:
            raise RuntimeError("AsyncSession is closed")
        if self._loop is not None and self._loop is not loop:
            raise RuntimeError("AsyncSession cannot move between event loops")
        self._loop = loop

    @staticmethod
    def _check(code: int) -> None:
        if code:
            raise CurlError(code, "multi: " + b.string(b.lib.curl_multi_strerror(code)).decode())

    async def _perform(self, curl: Curl) -> None:
        curl._require_idle()
        future: asyncio.Future[int] = asyncio.get_running_loop().create_future()
        key = b.address(curl._handle)
        self._check(b.lib.curl_multi_add_handle(self._multi, curl._handle))
        curl._active = True
        curl._callback_error = None
        self._pending[key] = (curl, future)
        if self._pump_task is None or self._pump_task.done():
            self._pump_task = asyncio.create_task(self._pump())
        try:
            code = await future
        finally:
            self._pending.pop(key, None)
            remove_code = b.lib.curl_multi_remove_handle(self._multi, curl._handle)
            curl._active = False
            self._check(remove_code)
        curl._finish(code)

    async def _pump(self) -> None:
        running, queued = b.pointer("int"), b.pointer("int")
        try:
            while self._pending:
                self._check(b.lib.curl_multi_perform(self._multi, running))
                while True:
                    message = b.lib.curl_multi_info_read(self._multi, queued)
                    if not message:
                        break
                    msg = message[0]
                    if msg.msg == 1:  # CURLMSG_DONE
                        entry = self._pending.get(b.address(msg.easy_handle))
                        if entry and not entry[1].done():
                            entry[1].set_result(int(msg.data.result))
                await asyncio.sleep(0.01)
        except Exception as exc:
            for _, future in self._pending.values():
                if not future.done():
                    future.set_exception(exc)

    async def request(self, method: str, url: str, **kwargs: Any) -> Response:
        self._check_loop()
        task = asyncio.current_task()
        assert task is not None
        self._tasks.add(task)
        try:
            async with self._limit:
                self._check_loop()
                with _SharedSession(self._share, **self._options) as session:
                    steps = session._request_steps(method, url, **kwargs)
                    try:
                        while True:
                            try:
                                curl = next(steps)
                            except StopIteration as done:
                                return done.value
                            await self._perform(curl)
                    finally:
                        steps.close()
        finally:
            self._tasks.discard(task)

    async def get(self, url: str, **kwargs: Any) -> Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> Response:
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> Response:
        return await self.request("PUT", url, **kwargs)

    async def patch(self, url: str, **kwargs: Any) -> Response:
        return await self.request("PATCH", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> Response:
        return await self.request("DELETE", url, **kwargs)

    async def head(self, url: str, **kwargs: Any) -> Response:
        kwargs.setdefault("allow_redirects", False)
        return await self.request("HEAD", url, **kwargs)

    async def options(self, url: str, **kwargs: Any) -> Response:
        return await self.request("OPTIONS", url, **kwargs)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._check_loop()
        self._closed = True
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._pump_task:
            await self._pump_task
        self._check(b.lib.curl_multi_cleanup(self._multi))
        code = b.lib.curl_share_cleanup(self._share)
        if code:
            raise CurlError(code, "could not clean up cookie share")

    async def __aenter__(self) -> AsyncSession:
        self._check_loop()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()
