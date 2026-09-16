"""Run: python examples/sync.py https://example.com"""

import sys

from curlight import Session

with Session(timeout=10) as session:
    response = session.get(sys.argv[1] if len(sys.argv) > 1 else "https://example.com")
    response.raise_for_status()
    print(response.status_code, response.headers.get("content-type"))
    print(response.text[:500])
