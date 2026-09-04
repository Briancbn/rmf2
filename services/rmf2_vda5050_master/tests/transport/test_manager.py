"""Tests for transport/manager.py — TransportManager, FanoutPublisher, FanoutSubscriber."""

from __future__ import annotations

import gc
import threading

from rmf2_vda5050_master.transport.base import (
    DeliveryMode,
    PublisherBase,
    ServerTransportBase,
    SubscriberBase,
)
from rmf2_vda5050_master.transport.manager import (
    FanoutSubscriber,
    TransportManager,
)

# ---------------------------------------------------------------------------
# Fake transport — no I/O
# ---------------------------------------------------------------------------


class _FakePublisher(PublisherBase):
    def __init__(self, topic, message_type, delivery_mode=DeliveryMode.TRANSIENT):
        super().__init__(topic, message_type)
        self.delivery_mode = delivery_mode
        self.published: list = []

    def publish(self, message):
        self.published.append(message)


class _FakeSubscriber(SubscriberBase):
    def __init__(self, topic, message_type):
        super().__init__(topic, message_type)
        self.cancelled = False

    def __del__(self):
        self.cancelled = True


class _FakeTransport(ServerTransportBase):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.publishers: list[_FakePublisher] = []
        self.subscribers: list[_FakeSubscriber] = []

    def create_publisher(
        self, message_type, topic, *, delivery_mode=DeliveryMode.TRANSIENT
    ):
        pub = _FakePublisher(topic, message_type, delivery_mode)
        self.publishers.append(pub)
        return pub

    def _subscribe(self, message_type, topic, callback) -> _FakeSubscriber:
        sub = _FakeSubscriber(topic, message_type)
        self.subscribers.append(sub)
        return sub

    def spin_once(self, timeout=0.0):
        pass

    def spin_some(self):
        pass


# ---------------------------------------------------------------------------
# TransportManager
# ---------------------------------------------------------------------------


def test_manager_prefix_applied_to_subscriber():
    manager = TransportManager(topic_prefix="rmf2_vm")
    t = _FakeTransport()
    manager.add_transport("a", t)

    _sub = manager.create_subscriber(str, "cmd", lambda msg: None)

    assert t.subscribers[0].topic == "rmf2_vm/cmd"


def test_manager_prefix_applied_to_publisher():
    manager = TransportManager(topic_prefix="rmf2_vm")
    t = _FakeTransport()
    manager.add_transport("a", t)

    pub = manager.create_fanout_publisher(str, "state")
    pub.publish("msg")

    assert t.publishers[0].topic == "rmf2_vm/state"


def test_manager_no_prefix_leaves_topic_unchanged():
    manager = TransportManager()
    t = _FakeTransport()
    manager.add_transport("a", t)

    _sub = manager.create_subscriber(str, "cmd", lambda msg: None)

    assert t.subscribers[0].topic == "cmd"


def test_remove_transport():
    manager = TransportManager()
    t = _FakeTransport()
    manager.add_transport("a", t)
    manager.remove_transport("a")
    assert manager.get_transport("a") is None


def test_get_transport_returns_correct():
    manager = TransportManager()
    t1, t2 = _FakeTransport(), _FakeTransport()
    manager.add_transport("a", t1)
    manager.add_transport("b", t2)
    assert manager.get_transport("a") is t1
    assert manager.get_transport("b") is t2


def test_get_transport_missing_returns_none():
    manager = TransportManager()
    assert manager.get_transport("nope") is None


def test_transports_returns_all():
    manager = TransportManager()
    t1, t2 = _FakeTransport(), _FakeTransport()
    manager.add_transport("a", t1)
    manager.add_transport("b", t2)
    assert set(manager.transports) == {t1, t2}


def test_transports_empty():
    assert TransportManager().transports == []


# ---------------------------------------------------------------------------
# FanoutPublisher
# ---------------------------------------------------------------------------


def test_fanout_publishes_to_all_transports():
    manager = TransportManager()
    t1, t2 = _FakeTransport(), _FakeTransport()
    manager.add_transport("a", t1)
    manager.add_transport("b", t2)

    pub = manager.create_fanout_publisher(str, "my/topic")
    pub.publish("hello")

    assert t1.publishers[0].published == ["hello"]
    assert t2.publishers[0].published == ["hello"]


def test_fanout_creates_publisher_lazily():
    manager = TransportManager()
    t = _FakeTransport()
    manager.add_transport("a", t)

    pub = manager.create_fanout_publisher(str, "topic")
    assert len(t.publishers) == 0

    pub.publish("x")
    assert len(t.publishers) == 1


def test_fanout_reuses_cached_publisher():
    manager = TransportManager()
    t = _FakeTransport()
    manager.add_transport("a", t)

    pub = manager.create_fanout_publisher(str, "topic")
    pub.publish("a")
    pub.publish("b")

    assert len(t.publishers) == 1
    assert t.publishers[0].published == ["a", "b"]


def test_fanout_evicts_removed_transport():
    manager = TransportManager()
    t1, t2 = _FakeTransport(), _FakeTransport()
    manager.add_transport("a", t1)
    manager.add_transport("b", t2)

    pub = manager.create_fanout_publisher(str, "topic")
    pub.publish("first")

    manager.remove_transport("b")
    pub.publish("second")

    assert t1.publishers[0].published == ["first", "second"]
    assert t2.publishers[0].published == ["first"]


def test_fanout_picks_up_new_transport():
    manager = TransportManager()
    t1 = _FakeTransport()
    manager.add_transport("a", t1)

    pub = manager.create_fanout_publisher(str, "topic")
    pub.publish("before")

    t2 = _FakeTransport()
    manager.add_transport("b", t2)
    pub.publish("after")

    assert t1.publishers[0].published == ["before", "after"]
    assert t2.publishers[0].published == ["after"]


def test_fanout_forwards_delivery_mode():
    manager = TransportManager()
    t = _FakeTransport()
    manager.add_transport("a", t)

    pub = manager.create_fanout_publisher(
        str, "topic", delivery_mode=DeliveryMode.PERSISTENT
    )
    pub.publish("msg")

    assert t.publishers[0].delivery_mode == DeliveryMode.PERSISTENT


def test_fanout_default_delivery_mode_is_transient():
    manager = TransportManager()
    t = _FakeTransport()
    manager.add_transport("a", t)

    pub = manager.create_fanout_publisher(str, "topic")
    pub.publish("msg")

    assert t.publishers[0].delivery_mode == DeliveryMode.TRANSIENT


def test_fanout_empty_manager_does_nothing():
    manager = TransportManager()
    pub = manager.create_fanout_publisher(str, "topic")
    pub.publish("msg")  # no error, no-op


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


def test_manager_concurrent_add_remove():
    """add_transport and remove_transport from many threads must not corrupt the dict."""
    manager = TransportManager()
    errors: list[Exception] = []

    def adder(name: str):
        try:
            manager.add_transport(name, _FakeTransport())
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    def remover(name: str):
        try:
            manager.remove_transport(name)
        except KeyError:
            pass
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = []
    for i in range(20):
        threads.append(threading.Thread(target=adder, args=(f"t{i}",)))
    for i in range(10):
        threads.append(threading.Thread(target=remover, args=(f"t{i}",)))

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []


def test_fanout_concurrent_publish():
    """Concurrent publish calls must not corrupt the publisher cache."""
    manager = TransportManager()
    for i in range(5):
        manager.add_transport(f"t{i}", _FakeTransport())

    pub = manager.create_fanout_publisher(str, "topic")
    errors: list[Exception] = []
    n = 30
    barrier = threading.Barrier(n)

    def worker():
        barrier.wait()
        try:
            pub.publish("msg")
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []


# ---------------------------------------------------------------------------
# FanoutSubscriber
# ---------------------------------------------------------------------------


def test_create_subscriber_returns_fanout_subscriber():
    manager = TransportManager()
    sub = manager.create_subscriber(str, "cmd", lambda msg: None)
    assert isinstance(sub, FanoutSubscriber)


def test_create_subscriber_creates_handle_on_existing_transport():
    manager = TransportManager()
    t = _FakeTransport()
    manager.add_transport("a", t)

    manager.create_subscriber(str, "cmd", lambda msg: None)

    assert len(t.subscribers) == 1


def test_add_transport_replays_subscriptions():
    manager = TransportManager()
    _sub = manager.create_subscriber(str, "cmd", lambda msg: None)

    t = _FakeTransport()
    manager.add_transport("a", t)

    assert len(t.subscribers) == 1


def test_add_transport_replays_multiple_subscriptions():
    manager = TransportManager()
    _sub1 = manager.create_subscriber(str, "cmd1", lambda msg: None)
    _sub2 = manager.create_subscriber(str, "cmd2", lambda msg: None)

    t = _FakeTransport()
    manager.add_transport("a", t)

    assert len(t.subscribers) == 2


def test_remove_transport_removes_handles_from_fanout_subscriber():
    manager = TransportManager()
    t = _FakeTransport()
    manager.add_transport("a", t)

    sub = manager.create_subscriber(str, "cmd", lambda msg: None)
    assert len(sub._handles) == 1

    manager.remove_transport("a")
    assert len(sub._handles) == 0


def test_fanout_subscriber_keeps_handles_alive():
    manager = TransportManager()
    t = _FakeTransport()
    manager.add_transport("a", t)

    sub = manager.create_subscriber(str, "cmd", lambda msg: None)

    handle = t.subscribers[0]
    assert handle in sub._handles.values()


def test_fanout_subscriber_gc_prunes_subscription():
    """When the FanoutSubscriber is GC'd, add_transport no longer notifies it."""
    manager = TransportManager()

    sub = manager.create_subscriber(str, "cmd", lambda msg: None)
    assert len(manager._subscriptions) == 1

    del sub
    gc.collect()

    t = _FakeTransport()
    manager.add_transport("a", t)  # triggers pruning of dead weakref

    assert len(t.subscribers) == 0
    assert len(manager._subscriptions) == 0


def test_fanout_subscriber_handles_lifetime_tied_to_subscriber():
    """Dropping the FanoutSubscriber drops its transport handles."""
    import weakref

    manager = TransportManager()
    t = _FakeTransport()
    manager.add_transport("a", t)

    sub = manager.create_subscriber(str, "cmd", lambda msg: None)
    handle_ref = weakref.ref(t.subscribers[0])
    t.subscribers.clear()  # release the extra ref held by the fake transport

    del sub
    gc.collect()

    assert handle_ref() is None
