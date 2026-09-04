from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from ...logger import get_logger
from .base import ExecutorBase

if TYPE_CHECKING:
    from ..manager import TransportManager

LOGGER = get_logger(__name__)


class SingleThreadedExecutor(ExecutorBase):
    """Runs all transports' ``spin_once`` in a single daemon thread, round-robin.

    Transports are sourced from the :class:`~.manager.TransportManager` at
    :meth:`start` time. Add or remove transports via the manager — the executor
    reflects whatever the manager holds when started.

    Usage::

        executor = SingleThreadedExecutor(manager)
        executor.start()
        ...
        executor.stop()
    """

    def __init__(self, manager: TransportManager, spin_timeout: float = 1.0) -> None:
        self._manager = manager
        self._spin_timeout = spin_timeout
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()

    def start(self) -> None:
        self._stopping.clear()
        self._thread = threading.Thread(
            target=self._spin_loop,
            daemon=True,
            name="executor",
        )
        self._thread.start()
        LOGGER.info(
            "SingleThreadedExecutor started (%d transport(s))",
            len(self._manager.transports),
        )

    def stop(self) -> None:
        self._stopping.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        LOGGER.info("SingleThreadedExecutor stopped")

    def _spin_loop(self) -> None:
        try:
            while not self._stopping.is_set():
                for transport in self._manager.transports:
                    transport.spin_once(timeout=self._spin_timeout)
        except Exception as exc:  # noqa: BLE001 — transport.spin_once may raise anything
            if not self._stopping.is_set():
                LOGGER.error("Executor spin error: %s", exc)
