"""Jupiter v6 Swap and Platform Fee Routing Engine.

Builds and queries Jupiter v6 quote and swap transactions with embedded
integrator platform fees (0.50% / 50 bps) for real-time SOL fee streaming.
"""

import time
from typing import Any

import httpx
from pydantic import BaseModel, Field
from solders.pubkey import Pubkey
from spl.token.instructions import get_associated_token_address


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


QUOTE_CACHE_TTL_SECONDS = 5.0

# Module-level so the cache is shared across short-lived JupiterRouter
# instances (cli.py/bot.py construct a fresh router per request) -- an
# instance-level cache would never see a second hit.
_quote_cache: dict[tuple[str, str, int, int], tuple[float, "QuoteResponse"]] = {}


def clear_quote_cache() -> None:
    """Clear the module-level quote cache (used by tests to avoid cross-test leakage)."""
    _quote_cache.clear()


def derive_fee_token_account(owner: str, mint: str) -> str:
    """Derive the Associated Token Account Jupiter requires for `feeAccount`.

    Jupiter's platform fee is transferred in the swap's output mint, into a
    token account of that mint -- not the fee wallet's raw address. Passing
    the wallet address directly builds a transaction that fails on-chain.
    """
    return str(
        get_associated_token_address(Pubkey.from_string(owner), Pubkey.from_string(mint))
    )


class JupiterRouter:
    """Async Client for Jupiter Swap Protocol with Platform Fee Integration."""

    def __init__(
        self,
        base_url: str = "https://api.jup.ag/swap/v1",
        timeout: float = 10.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(
            http2=True,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
            timeout=httpx.Timeout(connect=2.0, read=5.0, write=5.0, pool=5.0),
        )

    async def get_quote(self, req: QuoteRequest, use_cache: bool = True) -> QuoteResponse:
        """Fetch swap quote with platform fee embedded.

        Cached for QUOTE_CACHE_TTL_SECONDS so repeated taps on the same
        (mint, amount) don't re-hit Jupiter. Callers that immediately feed
        the quote into a swap transaction (e.g. run_swap) must pass
        use_cache=False -- a stale quote there risks building a swap against
        outdated pricing/liquidity.
        """
        cache_key = (req.input_mint, req.output_mint, req.amount_lamports, req.slippage_bps)
        if use_cache:
            cached = _quote_cache.get(cache_key)
            if cached is not None:
                cached_at, cached_quote = cached
                if time.monotonic() - cached_at < QUOTE_CACHE_TTL_SECONDS:
                    return cached_quote

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

        quote = QuoteResponse(
            input_mint=data["inputMint"],
            output_mint=data["outputMint"],
            in_amount=int(data["inAmount"]),
            out_amount=int(data["outAmount"]),
            price_impact_pct=float(data.get("priceImpactPct", 0.0)),
            platform_fee_amount=platform_fee_amount,
            raw_data=data,
        )
        if use_cache:
            _quote_cache[cache_key] = (time.monotonic(), quote)
        return quote

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
