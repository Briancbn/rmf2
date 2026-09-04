from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from ...logger import get_logger
from .base import ExecutorBase

if TYPE_CHECKING:
    from ..manager import TransportManager

LOGGER = get_logger(__name__)


class MultiThreadedExecutor(ExecutorBase):
    """Runs each transport's ``spin_once`` in its own dedicated daemon thread.

    Transports are sourced from the :class:`~.manager.TransportManager` at
    :meth:`start` time. Add or remove transports via the manager — the executor
    reflects whatever the manager holds when started.

    Usage::

        executor = MultiThreadedExecutor(manager)
        executor.start()
        ...
        executor.stop()
    """

    def __init__(self, manager: TransportManager, spin_timeout: float = 1.0) -> None:
        self._manager = manager
        self._spin_timeout = spin_timeout
        self._threads: list[threading.Thread] = []
        self._stopping = threading.Event()

    def start(self) -> None:
        self._stopping.clear()
        for transport in self._manager.transports:
            if not transport.needs_spin:
                continue
            thread = threading.Thread(
                target=self._spin_loop,
                args=(transport,),
                daemon=True,
                name=f"executor-{type(transport).__name__}",
            )
            thread.start()
            self._threads.append(thread)
        LOGGER.info(
            "MultiThreadedExecutor started (%d spin thread(s))", len(self._threads)
        )

    def stop(self) -> None:
        self._stopping.set()
        for thread in self._threads:
            thread.join(timeout=5)
        self._threads.clear()
        LOGGER.info("MultiThreadedExecutor stopped")

    def _spin_loop(self, transport) -> None:
        name = type(transport).__name__
        try:
            while not self._stopping.is_set():
                transport.spin_once(timeout=self._spin_timeout)
        except Exception as exc:  # noqa: BLE001 — transport.spin_once may raise anything
            if not self._stopping.is_set():
                LOGGER.error("Executor spin error (%s): %s", name, exc)
