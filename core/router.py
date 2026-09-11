"""Jupiter v6 Swap and Platform Fee Routing Engine.

Builds and queries Jupiter v6 quote and swap transactions with embedded
integrator platform fees (0.50% / 50 bps) for real-time SOL fee streaming.
"""

from typing import Any

import httpx
from pydantic import BaseModel, Field


class QuoteRequest(BaseModel):
    input_mint: str
    output_mint: str
    amount_lamports: int
    slippage_bps: int = 50
    platform_fee_bps: int = 50


class QuoteResponse(BaseModel):
    input_mint: str
    output_mint: str
    in_amount: int
    out_amount: int
    price_impact_pct: float
    platform_fee_amount: int | None = None
    raw_data: dict[str, Any] = Field(default_factory=dict)


class SwapRequest(BaseModel):
    quote_response: dict[str, Any]
    user_public_key: str
    fee_account: str | None = None
    dynamic_compute_unit_limit: bool = True
    prioritization_fee_lamports: int | None = None


class JupiterRouter:
    """Async Client for Jupiter Swap Protocol with Platform Fee Integration."""

    def __init__(
        self,
        base_url: str = "https://api.jup.ag/swap/v1",
        timeout: float = 10.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=timeout)

    async def get_quote(self, req: QuoteRequest) -> QuoteResponse:
        """Fetch swap quote with platform fee embedded."""
        url = f"{self.base_url}/quote"
        params = {
            "inputMint": req.input_mint,
            "outputMint": req.output_mint,
            "amount": req.amount_lamports,
            "slippageBps": req.slippage_bps,
            "platformFeeBps": req.platform_fee_bps,
        }

        resp = await self.client.get(url, params=params)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Jupiter quote failed ({resp.status_code}): {resp.text}"
            )

        data = resp.json()
        platform_fee_info = data.get("platformFee") or {}
        platform_fee_amount = (
            int(platform_fee_info.get("amount", 0))
            if "amount" in platform_fee_info
            else None
        )

        return QuoteResponse(
            input_mint=data["inputMint"],
            output_mint=data["outputMint"],
            in_amount=int(data["inAmount"]),
            out_amount=int(data["outAmount"]),
            price_impact_pct=float(data.get("priceImpactPct", 0.0)),
            platform_fee_amount=platform_fee_amount,
            raw_data=data,
        )

    async def get_swap_transaction(self, req: SwapRequest) -> str:
        """Construct serialized swap transaction containing platform fee transfer."""
        url = f"{self.base_url}/swap"
        payload: dict[str, Any] = {
            "quoteResponse": req.quote_response,
            "userPublicKey": req.user_public_key,
            "dynamicComputeUnitLimit": req.dynamic_compute_unit_limit,
        }

        if req.fee_account:
            payload["feeAccount"] = req.fee_account

        if req.prioritization_fee_lamports is not None:
            payload["prioritizationFeeLamports"] = req.prioritization_fee_lamports

        resp = await self.client.post(url, json=payload)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Jupiter swap transaction build failed ({resp.status_code}): {resp.text}"
            )

        data = resp.json()
        tx_base64 = data.get("swapTransaction")
        if not tx_base64:
            raise ValueError("Jupiter response did not contain swapTransaction")

        return str(tx_base64)

    async def close(self) -> None:
        """Close HTTP connection pool."""
        await self.client.aclose()
