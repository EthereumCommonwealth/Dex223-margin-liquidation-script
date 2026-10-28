from __future__ import annotations
from dataclasses import dataclass

from loguru import logger
from web3 import AsyncWeb3, Web3
from web3.contract import AsyncContract
from web3.exceptions import ContractLogicError

from core.utils.w3 import ADDRESS_ZERO

# The only factory function the bot needs: Dex223Factory.getPool(tokenA, tokenB, fee).
FACTORY_GET_POOL_ABI = [
    {
        "type": "function",
        "name": "getPool",
        "stateMutability": "view",
        "inputs": [
            {"name": "tokenA", "type": "address"},
            {"name": "tokenB", "type": "address"},
            {"name": "fee", "type": "uint24"},
        ],
        "outputs": [{"name": "pool", "type": "address"}],
    }
]


@dataclass
class SubjectToLiquidationDTO:
    status: bool
    liquidator: str | None
    frozen_ts: int | None
    predict_timestamp: int | None
    liquidated: bool


class MarginModuleClient:
    """Encapsulates interaction with MarginModule (ABI/decoding/calls)."""

    def __init__(
            self,
            w3: AsyncWeb3,
            address: str,
            abi: list[dict]
    ):
        self.w3 = w3
        self.address = address
        self.abi = abi
        self.contract: AsyncContract = w3.eth.contract(address=Web3.to_checksum_address(address), abi=abi)

    async def get_position_pools(self, position_id: int, fee_tiers: list[int]) -> list[str]:
        """Every factory pool between one of the position's non-base assets and the order's base
        asset, one per fee tier; zero addresses where no pool exists (the repository drops them).

        The module used to offer getPositionActualPools() for this. It was removed from the contract
        to fit EIP-170, and it was wrong anyway: it wrote pool (asset i, tier j) to slot i + j, so with
        more than one asset the slots overlapped and most pools were lost.
        """
        position = await self.contract.functions.positions(position_id).call()
        order = await self.contract.functions.orders(position[0]).call()  # [0] orderId
        base_asset = order[6]  # owner, id, whitelist, interestRate, duration, minLoan, baseAsset, ...
        assets = await self.contract.functions.getPositionAssets(position_id).call()
        factory = self.w3.eth.contract(
            address=await self.contract.functions.factory().call(), abi=FACTORY_GET_POOL_ABI
        )
        pools: list[str] = []
        for asset in assets:
            if asset.lower() == base_asset.lower():
                continue
            for fee in fee_tiers:
                pools.append(await factory.functions.getPool(asset, base_asset, fee).call())
        return pools

    async def subject_to_liquidation(self, position_id: int) -> SubjectToLiquidationDTO:
        try:
            status, liquidator, frozen_ts, liquidated, predict_timestamp = \
                await self.contract.functions.subjectToLiquidationExtended(
                    position_id
                ).call()
            logger.debug(
                f'subjectToLiquidationExtended status: {status},'
                f'liquidator: {liquidator}, '
                f'frozen_ts: {frozen_ts}, '
                f'liquidated: {liquidated}, '
                f'position_id: {position_id}, '
                f"predict_timestamp: {predict_timestamp}"
            )
        except ContractLogicError as e:
            logger.error(f"subjectToLiquidationExtended reverted for {position_id}: {e}")
            return SubjectToLiquidationDTO(False, None, None, None, False)
        return SubjectToLiquidationDTO(
            status=status,
            frozen_ts=frozen_ts,
            liquidator=None if liquidator == ADDRESS_ZERO else liquidator,
            liquidated=liquidated,
            predict_timestamp=predict_timestamp if predict_timestamp != 0 else None,
        )

    async def position_index(self) -> int:
        return await self.contract.functions.positionIndex().call()
