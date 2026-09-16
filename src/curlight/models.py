"""HTTP value objects."""
from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from email.message import Message
from typing import Any

from .exceptions import HTTPError


class Headers(Mapping[str, str]):
    """Immutable case-insensitive headers preserving duplicate fields and original casing."""

    def __init__(self, values: Mapping[str, str] | Iterable[tuple[str, str]] = ()) -> None:
        self._items = tuple(values.items() if isinstance(values, Mapping) else values)

    def __getitem__(self, name: str) -> str:
        values = self.get_list(name)
        if not values:
            raise KeyError(name)
        return ", ".join(values)

    def get_list(self, name: str) -> list[str]:
        """Return individual values (especially important for Set-Cookie)."""
        return [v for k, v in self._items if k.lower() == name.lower()]

    def multi_items(self) -> tuple[tuple[str, str], ...]:
        return self._items

    def __iter__(self) -> Iterator[str]:
        seen = set()
        for key, _ in self._items:
            if key.lower() not in seen:
                seen.add(key.lower())
                yield key

    def __len__(self) -> int:
        return len({key.lower() for key, _ in self._items})


@dataclass(frozen=True)
class Response:
    status_code: int
    url: str
    headers: Headers = field(default_factory=Headers)
    content: bytes = b""
    reason: str = ""
    elapsed: float = 0.0
    history: tuple[Response, ...] = ()

    @property
    def encoding(self) -> str:
        message = Message()
        message["content-type"] = self.headers.get("content-type", "")
        return message.get_content_charset() or "utf-8"

    @property
    def text(self) -> str:
        try:
            return self.content.decode(self.encoding, "replace")
        except LookupError:
            return self.content.decode("utf-8", "replace")

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self, **kwargs: Any) -> Any:
        return json.loads(self.content, **kwargs)

    def raise_for_status(self) -> Response:
        if self.status_code >= 400:
            raise HTTPError(self)
        return self
