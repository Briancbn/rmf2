from __future__ import annotations

from abc import ABC, abstractmethod


class ExecutorBase(ABC):
    """Drives the spin loop for one or more transports."""

    @abstractmethod
    def start(self) -> None:
        """Begin spinning all registered transports."""

    @abstractmethod
    def stop(self) -> None:
        """Stop spinning and join any background threads."""
