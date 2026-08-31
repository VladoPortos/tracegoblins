from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.awx.sync import (
    controller_lock_key,
    release_controller_lock,
    try_acquire_controller_lock,
)


def test_controller_lock_key_is_stable_signed_64bit():
    cid = uuid.UUID("11111111-2222-3333-4444-555555555555")
    k1 = controller_lock_key(cid)
    k2 = controller_lock_key(cid)
    assert k1 == k2  # stable
    assert -(2**63) <= k1 < 2**63  # fits a signed bigint (pg advisory-lock key domain)
    # distinct uuids -> (almost surely) distinct keys
    assert controller_lock_key(uuid.uuid4()) != controller_lock_key(uuid.uuid4())


@pytest.mark.db_per_test
async def test_lock_held_on_one_connection_blocks_another(engine):
    """The advisory lock is bound to the CONNECTION it was taken on: held on conn A it is
    NOT acquirable on conn B; releasing on A frees it. (try_acquire/release take a
    raw AsyncConnection, NOT a Session — that's the connection-pinning fix.)"""
    key = controller_lock_key(uuid.uuid4())
    async with engine.connect() as a, engine.connect() as b:
        assert await try_acquire_controller_lock(a, key) is True
        assert await try_acquire_controller_lock(b, key) is False  # A holds it
        await release_controller_lock(a, key)
        # pg frees the lock on conn A immediately
        assert await try_acquire_controller_lock(b, key) is True
        await release_controller_lock(b, key)
        assert await b.scalar(text("SELECT 1")) == 1
