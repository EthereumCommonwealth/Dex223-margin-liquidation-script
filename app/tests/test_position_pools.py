"""
get_position_pools() derives a position's pools from the factory. The module's
getPositionActualPools() it used to call was removed from the contract (EIP-170 headroom) and was
wrong anyway: with more than one asset it overwrote most slots.
"""
from types import SimpleNamespace

import pytest

from core.contracts import MarginModuleClient

BASE = "0x" + "11" * 20
COL = "0x" + "22" * 20
THIRD = "0x" + "33" * 20
FACTORY = "0x" + "44" * 20
MODULE = "0x" + "55" * 20
ZERO = "0x" + "00" * 20
FEE_TIERS = [500, 3000, 10000]

POOLS = {
    (COL, 500): "0x" + "a1" * 20,
    (COL, 3000): ZERO,
    (COL, 10000): "0x" + "a3" * 20,
    (THIRD, 500): ZERO,
    (THIRD, 3000): "0x" + "b2" * 20,
    (THIRD, 10000): ZERO,
}


class _Call:
    def __init__(self, value):
        self._value = value

    async def call(self):
        return self._value


class _Functions:
    """contract.functions.<name>(*args).call() backed by a table of python callables."""

    def __init__(self, table):
        self._table = table

    def __getattr__(self, name):
        fn = self._table[name]
        return lambda *args: _Call(fn(*args))


def _contract(table):
    return SimpleNamespace(functions=_Functions(table))


class _Eth:
    def __init__(self, contracts):
        self._contracts = contracts

    def contract(self, address, abi):
        return self._contracts[address.lower()]


def _client():
    module = _contract({
        "positions": lambda pid: (7, "0xowner"),  # orderId first, as in the public getter
        # owner, id, whitelist, interestRate, duration, minLoan, baseAsset, ...
        "orders": lambda oid: ("0xowner", oid, b"", 0, 0, 0, BASE),
        "getPositionAssets": lambda pid: [BASE, COL, THIRD],
        "factory": lambda: FACTORY,
    })
    factory = _contract({
        "getPool": lambda a, b, fee: POOLS[(a, fee)] if b == BASE else ZERO,
    })
    w3 = SimpleNamespace(eth=_Eth({MODULE: module, FACTORY: factory}))
    return MarginModuleClient(w3, MODULE, abi=[])


@pytest.mark.asyncio
async def test_pools_cover_every_non_base_asset_and_fee_tier():
    pools = await _client().get_position_pools(1, FEE_TIERS)
    # asset-major, fee-tier-minor; the base asset itself is never paired with itself
    assert pools == [
        POOLS[(COL, 500)], ZERO, POOLS[(COL, 10000)],
        ZERO, POOLS[(THIRD, 3000)], ZERO,
    ]


@pytest.mark.asyncio
async def test_base_only_position_has_no_pools():
    client = _client()
    client.contract.functions._table["getPositionAssets"] = lambda pid: [BASE]
    assert await client.get_position_pools(1, FEE_TIERS) == []
