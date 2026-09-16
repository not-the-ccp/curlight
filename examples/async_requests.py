"""Run: python examples/async_requests.py URL [URL ...]"""

import asyncio
import sys

from curlight import AsyncSession


async def main():
    async with AsyncSession(max_connections=5, timeout=10) as session:
        responses = await asyncio.gather(
            *(session.get(url) for url in sys.argv[1:] or ["https://example.com"])
        )
        for response in responses:
            print(response.url, response.status_code, len(response.content))


asyncio.run(main())
