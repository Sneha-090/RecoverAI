from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.models import RecoveryReservation
from app.services.reservations import (
    finish_recovery, reserve_recovery, reserve_webhook,
)


@pytest.fixture
def sessions(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'claims.db').as_posix()}")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)
    engine.dispose()


@pytest.mark.parametrize("kind", ["webhook", "payment"])
def test_simultaneous_requests_have_exactly_one_owner(sessions, kind):
    barrier = Barrier(2)

    def reserve():
        with sessions() as db:
            barrier.wait(timeout=5)
            if kind == "webhook":
                return reserve_webhook(db, "evt_shared") is None
            return reserve_recovery(db, "pay_shared") is not None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: reserve(), range(2)))
    assert sorted(results) == [False, True]


def test_waiting_phase_can_be_claimed_only_once(sessions):
    with sessions() as db:
        owner = reserve_recovery(db, "pay_shared")
        finish_recovery(db, "pay_shared", owner, "awaiting_outcome")
    barrier = Barrier(2)

    def reserve():
        with sessions() as db:
            barrier.wait(timeout=5)
            return reserve_recovery(db, "pay_shared", "awaiting_outcome") is not None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: reserve(), range(2)))
    assert sorted(results) == [False, True]


def test_previous_owner_cannot_release_new_owners_claim(sessions):
    with sessions() as db:
        first = reserve_recovery(db, "pay_shared")
        finish_recovery(db, "pay_shared", first, "pending_review")
        second = reserve_recovery(db, "pay_shared", "pending_review")
        finish_recovery(db, "pay_shared", first)
        assert db.get(RecoveryReservation, "pay_shared").owner == second


@pytest.mark.parametrize("state", ["processing", "needs_reconciliation", "awaiting_outcome"])
def test_restart_does_not_automatically_retry_durable_claim(sessions, state):
    with sessions() as db:
        owner = reserve_recovery(db, "pay_shared")
        finish_recovery(db, "pay_shared", owner, state)
    with sessions() as restarted:
        assert reserve_recovery(restarted, "pay_shared") is None
