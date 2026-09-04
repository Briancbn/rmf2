from __future__ import annotations

import threading
import weakref
from collections.abc import Callable
from typing import TypeVar

from .base import PublisherBase, ServerTransportBase, SubscriberBase

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Fanout publisher — spans multiple transports
# ---------------------------------------------------------------------------


class FanoutPublisher(PublisherBase[T]):
    """Publisher that fans out to all transports currently in the manager.

    Publishers are cached per transport and created on first use. Transports
    removed from the manager are evicted from the cache on the next publish.
    """

    def __init__(
        self,
        manager: TransportManager,
        topic: str,
        message_type: type[T],
        **pub_kwargs,
    ) -> None:
        super().__init__(topic, message_type)
        self._manager = manager
        self._pub_kwargs = pub_kwargs
        self._cache: dict[ServerTransportBase, PublisherBase[T]] = {}
        self._lock = threading.Lock()

    def publish(self, message: T) -> None:
        with self._lock:
            live = set(self._manager.transports)
            for stale in [t for t in self._cache if t not in live]:
                del self._cache[stale]
            for transport in live:
                if transport not in self._cache:
                    self._cache[transport] = transport.create_publisher(
                        self.message_type, self.topic, **self._pub_kwargs
                    )
            pubs = list(self._cache.values())
        for pub in pubs:
            pub.publish(message)


# ---------------------------------------------------------------------------
# Fanout subscriber — spans multiple transports
# ---------------------------------------------------------------------------


class FanoutSubscriber:
    """Subscriber that registers a single callback across all transports in a manager.

    Holds one :class:`SubscriberBase` handle per transport, keeping each consumer
    alive. Dropping this object cancels every consumer via ``__del__`` on the
    individual handles.

    The manager stores only a weakref, so lifetime is controlled by whoever holds
    the strong reference (typically the observer that created it).
    """

    def __init__(self, message_type: type, topic: str, callback: Callable) -> None:
        self._message_type = message_type
        self._topic = topic
        self._callback = callback
        self._handles: dict[ServerTransportBase, SubscriberBase] = {}
        self._lock = threading.Lock()

    def _on_transport_added(self, transport: ServerTransportBase) -> None:
        handle = transport._subscribe(self._message_type, self._topic, self._callback)
        with self._lock:
            self._handles[transport] = handle

    def _on_transport_removed(self, transport: ServerTransportBase) -> None:
        with self._lock:
            self._handles.pop(transport, None)


# ---------------------------------------------------------------------------
# TransportManager
# ---------------------------------------------------------------------------


class TransportManager:
    """Container for named :class:`ServerTransportBase` transports.

    Transports are registered by name so they can be looked up and removed
    individually at runtime (e.g. from a REST API handler)::

        manager = TransportManager()
        manager.add_transport("amqp", amqp_transport)
        transport = manager.get_transport("amqp")
        manager.remove_transport("amqp")

    Use :meth:`create_subscriber` to register subscriptions that automatically
    follow transports added later. Use :meth:`create_fanout_publisher` for
    publishers that fan out across all transports.
    """

    def __init__(self, topic_prefix: str | None = None) -> None:
        self.topic_prefix = topic_prefix
        self._transports: dict[str, ServerTransportBase] = {}
        # topic -> weakref[FanoutSubscriber]; pruned on add_transport when GC'd
        self._subscriptions: dict[str, weakref.ref[FanoutSubscriber]] = {}
        self._lock = threading.RLock()

    def _full_topic(self, topic: str) -> str:
        return f"{self.topic_prefix}/{topic}" if self.topic_prefix else topic

    @property
    def transports(self) -> list[ServerTransportBase]:
        with self._lock:
            return list(self._transports.values())

    def create_subscriber(
        self, message_type: type, topic: str, callback: Callable
    ) -> FanoutSubscriber:
        """Register a subscription on all current and future transports.

        Returns a :class:`FanoutSubscriber` whose lifetime controls the consumers.
        Hold a strong reference to keep them alive; drop it to cancel them all.
        Registering the same topic again replaces the previous entry.
        """
        fanout_subscriber = FanoutSubscriber(
            message_type, self._full_topic(topic), callback
        )
        with self._lock:
            for transport in self._transports.values():
                fanout_subscriber._on_transport_added(transport)
            self._subscriptions[topic] = weakref.ref(fanout_subscriber)
        return fanout_subscriber

    def add_transport(self, name: str, transport: ServerTransportBase) -> None:
        """Register ``transport`` under ``name``."""
        with self._lock:
            self._transports[name] = transport
            dead: list[str] = []
            for topic, ref in self._subscriptions.items():
                fanout_subscriber = ref()
                if fanout_subscriber is not None:
                    fanout_subscriber._on_transport_added(transport)
                else:
                    dead.append(topic)
            for topic in dead:
                del self._subscriptions[topic]

    def remove_transport(self, name: str) -> None:
        """Remove the transport registered under ``name``."""
        with self._lock:
            transport = self._transports.pop(name)
            for ref in self._subscriptions.values():
                fanout_subscriber = ref()
                if fanout_subscriber is not None:
                    fanout_subscriber._on_transport_removed(transport)

    def get_transport(self, name: str) -> ServerTransportBase | None:
        """Return the transport registered under ``name``, or ``None``."""
        with self._lock:
            return self._transports.get(name)

    def create_fanout_publisher(
        self, message_type: type[T], topic: str, **pub_kwargs
    ) -> FanoutPublisher[T]:
        """Return a :class:`FanoutPublisher` that fans out to all current transports.

        The publisher stays live — transports added or removed from the manager
        after creation are reflected automatically on the next :meth:`~FanoutPublisher.publish`.
        Extra keyword arguments (e.g. ``delivery_mode``) are forwarded to each
        underlying :meth:`~ServerTransportBase.create_publisher` call.
        """
        return FanoutPublisher(
            self, self._full_topic(topic), message_type, **pub_kwargs
        )
