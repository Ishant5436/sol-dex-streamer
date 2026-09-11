"""Real-time Token Discovery and Liquidity Radar for Solana DEXs.

Streams trending, high-momentum tokens from DexScreener and Raydium/Pump.fun,
enforcing minimum liquidity ($10k+) and volume ($25k+) filters to protect users from honeypots.
"""

from typing import Any

import httpx
from pydantic import BaseModel, Field


class TokenInfo(BaseModel):
    mint: str
    symbol: str
    name: str
    price_usd: float = 0.0
    volume_24h_usd: float = 0.0
    liquidity_usd: float = 0.0
    price_change_5m_pct: float = 0.0
    dex_id: str = "unknown"
    raw_data: dict[str, Any] = Field(default_factory=dict)


class TokenRadar:
    """Async Discovery Radar for High-Volume Solana Tokens."""

    def __init__(
        self,
        min_liquidity_usd: float = 10000.0,
        min_volume_24h_usd: float = 25000.0,
        timeout: float = 8.0,
    ):
        self.min_liquidity_usd = min_liquidity_usd
        self.min_volume_24h_usd = min_volume_24h_usd
        self.client = httpx.AsyncClient(timeout=timeout)

    def filter_tokens(self, raw_pairs: list[dict[str, Any]]) -> list[TokenInfo]:
        """Apply strict liquidity, volume, and deduplication filters."""
        seen_mints = set()
        filtered: list[TokenInfo] = []

        for p in raw_pairs:
            base = p.get("baseToken") or {}
            mint = base.get("address")
            if not mint or mint in seen_mints:
                continue

            liq_data = p.get("liquidity") or {}
            liq_usd = float(liq_data.get("usd", 0.0) or 0.0)

            vol_data = p.get("volume") or {}
            vol_24h = float(vol_data.get("h24", 0.0) or 0.0)

            if liq_usd < self.min_liquidity_usd or vol_24h < self.min_volume_24h_usd:
                continue

            price_change = p.get("priceChange") or {}
            m5_change = float(price_change.get("m5", 0.0) or 0.0)

            price_usd = float(p.get("priceUsd", 0.0) or 0.0)
            symbol = base.get("symbol", "UNKNOWN")
            name = base.get("name", symbol)
            dex_id = p.get("dexId", "raydium")

            seen_mints.add(mint)
            filtered.append(
                TokenInfo(
                    mint=mint,
                    symbol=symbol,
                    name=name,
                    price_usd=price_usd,
                    volume_24h_usd=vol_24h,
                    liquidity_usd=liq_usd,
                    price_change_5m_pct=m5_change,
                    dex_id=dex_id,
                    raw_data=p,
                )
            )

        return filtered

    async def fetch_trending_tokens(self, limit: int = 10) -> list[TokenInfo]:
        """Fetch trending pairs on Solana from DexScreener."""
        url = "https://api.dexscreener.com/latest/dex/search?q=SOL"
        try:
            resp = await self.client.get(url)
            if resp.status_code != 200:
                return []

            data = resp.json()
            pairs = data if isinstance(data, list) else data.get("pairs", [])
            tokens = self.filter_tokens(pairs)
            return tokens[:limit]
        except Exception:
            return []

    async def close(self) -> None:
        """Close client connection."""
        await self.client.aclose()
