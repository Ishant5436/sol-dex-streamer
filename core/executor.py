"""Jito MEV Anti-Sandwich Bundler and Transaction Execution Engine.

Packs Jupiter swap transactions with private Jito validator tips,
bypassing the public Solana mempool to eliminate frontrunning and sandwich attacks.
"""

import base64
import random
from typing import Any

import httpx
from pydantic import BaseModel
from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import VersionedTransaction

# Official Jito BlockEngine tip accounts
JITO_TIP_ACCOUNTS: list[str] = [
    "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
    "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bU7gRe",
    "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY",
    "ADaUMid9yfUytqMBgopwjb2DTLSokTSzL1zt6iGPaS49",
    "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh",
    "ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt",
    "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL",
    "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT",
]


class JitoTipConfig(BaseModel):
    tip_lamports: int = 10000  # 0.00001 SOL
    block_engine_url: str = (
        "https://mainnet.block-engine.jito.wtf/api/v1/bundles"
    )


class JitoBundler:
    """Dispatches MEV-protected transaction bundles directly to Jito validators."""

    def __init__(
        self,
        block_engine_url: str = "https://mainnet.block-engine.jito.wtf/api/v1/bundles",
        timeout: float = 10.0,
    ):
        self.block_engine_url = block_engine_url
        self.client = httpx.AsyncClient(timeout=timeout)

    def get_random_tip_account(self) -> Pubkey:
        """Select a random Jito tip account to balance validator distribution."""
        tip_str = random.choice(JITO_TIP_ACCOUNTS)
        return Pubkey.from_string(tip_str)

    def create_tip_transaction(
        self,
        payer: Keypair,
        tip_lamports: int = 10000,
        recent_blockhash: str | None = None,
    ) -> VersionedTransaction:
        """Create and sign a standalone Jito tip transfer transaction."""
        tip_account = self.get_random_tip_account()
        ix = transfer(
            TransferParams(
                from_pubkey=payer.pubkey(),
                to_pubkey=tip_account,
                lamports=tip_lamports,
            )
        )

        bhash = (
            Hash.from_string(recent_blockhash)
            if recent_blockhash
            else Hash.default()
        )
        msg = MessageV0.try_compile(
            payer=payer.pubkey(),
            instructions=[ix],
            address_lookup_table_accounts=[],
            recent_blockhash=bhash,
        )
        return VersionedTransaction(msg, [payer])

    def sign_jupiter_transaction(
        self,
        swap_tx_base64: str,
        payer: Keypair,
    ) -> VersionedTransaction:
        """Deserialize and sign Jupiter's base64 VersionedTransaction."""
        raw_bytes = base64.b64decode(swap_tx_base64)
        tx = VersionedTransaction.from_bytes(raw_bytes)
        # Sign transaction with user keypair
        return VersionedTransaction(tx.message, [payer])

    async def send_bundle(self, encoded_transactions: list[str]) -> str:
        """Send bundle to Jito Block Engine JSON-RPC API."""
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendBundle",
            "params": [encoded_transactions],
        }

        resp = await self.client.post(self.block_engine_url, json=payload)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Jito BlockEngine HTTP error ({resp.status_code}): {resp.text}"
            )

        data = resp.json()
        if "error" in data:
            raise RuntimeError(
                f"Jito bundle submission failed: {data['error']}"
            )

        bundle_id = data.get("result")
        if not bundle_id:
            raise ValueError("Jito response did not return a bundle ID")

        return str(bundle_id)

    async def close(self) -> None:
        """Close HTTP client."""
        await self.client.aclose()
