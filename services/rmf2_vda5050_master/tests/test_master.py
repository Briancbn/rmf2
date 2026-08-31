from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from rmf2_vda5050_master.db_models import AgvRecord, MasterHeartbeat
from rmf2_vda5050_master.master import _Heartbeat, _MasterObserver, _upsert_agv
from rmf2_vda5050_master.models import AgvConfig


MASTER_ID = "test-master"
MFR = "TestCo"
SN = "001"


# ---------------------------------------------------------------------------
# _upsert_agv
# ---------------------------------------------------------------------------

def test_upsert_agv_creates_record(session):
    _upsert_agv(session, MFR, SN, is_onboarded=True)
    session.commit()
    record = session.get(AgvRecord, (MFR, SN))
    assert record is not None
    assert record.is_onboarded is True


def test_upsert_agv_updates_existing(session):
    _upsert_agv(session, MFR, SN, is_online=False)
    session.commit()
    _upsert_agv(session, MFR, SN, is_online=True)
    session.commit()
    assert session.get(AgvRecord, (MFR, SN)).is_online is True


# ---------------------------------------------------------------------------
# _Heartbeat
# ---------------------------------------------------------------------------

def test_heartbeat_writes_on_start(session_factory):
    hb = _Heartbeat(session_factory, MASTER_ID, interval=60)
    hb.start()
    time.sleep(0.2)
    hb.stop()
    with session_factory() as session:
        record = session.get(MasterHeartbeat, MASTER_ID)
    assert record is not None
    assert record.master_id == MASTER_ID


def test_heartbeat_updates_last_seen(session_factory):
    hb = _Heartbeat(session_factory, MASTER_ID, interval=1)
    hb.start()
    time.sleep(0.2)
    with session_factory() as session:
        first = session.get(MasterHeartbeat, MASTER_ID).last_seen_at
    time.sleep(1.2)
    with session_factory() as session:
        second = session.get(MasterHeartbeat, MASTER_ID).last_seen_at
    hb.stop()
    assert second > first


def test_heartbeat_stops_cleanly(session_factory):
    hb = _Heartbeat(session_factory, MASTER_ID, interval=60)
    hb.start()
    hb.stop()
    assert not hb._thread.is_alive()


# ---------------------------------------------------------------------------
# _MasterObserver
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_master():
    return MagicMock()


@pytest.fixture
def agvs():
    return [AgvConfig(manufacturer=MFR, serial_number=SN)]


@pytest.fixture
def observer(mock_master, agvs, session_factory):
    return _MasterObserver(mock_master, agvs, session_factory, MASTER_ID)


def test_on_connect_sets_online(observer, session_factory):
    observer.on_connect((MFR, SN))
    with session_factory() as session:
        record = session.get(AgvRecord, (MFR, SN))
    assert record.is_online is True
    assert record.master_id == MASTER_ID


def test_on_connect_sends_state_request(observer, mock_master):
    observer.on_connect((MFR, SN))
    mock_master.publish_instant_actions.assert_called_once()


def test_on_offline_sets_offline(observer, session_factory):
    with session_factory() as session:
        _upsert_agv(session, MFR, SN, is_online=True)
        session.commit()
    observer.on_offline((MFR, SN))
    with session_factory() as session:
        assert session.get(AgvRecord, (MFR, SN)).is_online is False


def test_on_connection_broken_sets_offline(observer, session_factory):
    with session_factory() as session:
        _upsert_agv(session, MFR, SN, is_online=True)
        session.commit()
    observer.on_connection_broken((MFR, SN))
    with session_factory() as session:
        assert session.get(AgvRecord, (MFR, SN)).is_online is False


def test_on_state_writes_state_json(observer, session_factory):
    mock_state = MagicMock()
    mock_state.json.return_value = {"manufacturer": MFR, "serialNumber": SN, "orderId": "x"}
    observer.on_state((MFR, SN), mock_state)
    with session_factory() as session:
        record = session.get(AgvRecord, (MFR, SN))
    assert record is not None
    assert record.state_json is not None
    assert '"orderId": "x"' in record.state_json
