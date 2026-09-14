"""Callback adapter working around make_raw_callback's arity heuristic.

``make_raw_callback`` (see ``base.py``) decides whether a subscriber callback wants
``(topic, message)`` or just ``(message)`` by counting
``inspect.signature(callback).parameters`` — including parameters with defaults. A callback
shaped like ``lambda payload, id=robot_id: ...`` (closing over a value via a defaulted second
parameter) has two parameters even though only one is meant to be supplied by the transport,
so it gets mis-detected as wanting two args and receives the topic string and the
deserialized message swapped into the wrong slots.

Wrapping such a callback in :class:`WrappedCallback` (whose ``__call__`` exposes exactly one
required parameter) always resolves correctly. The instance is itself directly callable, so
it can double as both the subscription target and the stored reference kept for later direct
invocation, avoiding a separate inner closure at each call site.

Optional ``pre``/``post`` hooks run immediately before/after ``callback`` (e.g. persisting a
message to the database before handing it to the real handler), so call sites that need extra
side effects don't have to write their own wrapping closure either.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Generic, TypeVar

T = TypeVar("T")


class WrappedCallback(Generic[T]):
    def __init__(
        self,
        callback: Callable[[T], None],
        *,
        pre: Callable[[T], None] | None = None,
        post: Callable[[T], None] | None = None,
    ) -> None:
        self._callback = callback
        self._pre = pre
        self._post = post

    def __call__(self, message: T) -> None:
        if self._pre is not None:
            self._pre(message)
        self._callback(message)
        if self._post is not None:
            self._post(message)
