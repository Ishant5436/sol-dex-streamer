"""Token Safety and Anti-Rug Audit Client.

Queries RugCheck for mint/freeze authority status and holder concentration
so traders see a basic rug-risk signal before acting on a scan or quote.

Uses the full `/report` endpoint, not `/report/summary` -- the summary
response only carries an aggregate risk score and a sparse `risks` list; it
does not expose `mintAuthority`, `freezeAuthority`, or `topHolders` at all
(confirmed live against api.rugcheck.xyz).
"""

import time

import httpx
from pydantic import BaseModel

SAFETY_CACHE_TTL_SECONDS = 300.0

_safety_cache: dict[str, tuple[float, "TokenSafetyReport"]] = {}


def clear_safety_cache() -> None:
    """Clear the module-level safety cache (used by tests)."""
    _safety_cache.clear()


class TokenSafetyReport(BaseModel):
    mint: str
    available: bool = True
    mint_authority_revoked: bool | None = None
    freeze_authority_revoked: bool | None = None
    top10_holder_pct: float | None = None

    def mint_badge(self) -> str:
        if not self.available or self.mint_authority_revoked is None:
            return "❔ Mint Unknown"
        return "✅ Mint Disabled" if self.mint_authority_revoked else "⚠️ Mint Active"

    def freeze_badge(self) -> str:
        if not self.available or self.freeze_authority_revoked is None:
            return "❔ Freeze Unknown"
        return "✅ Freeze Disabled" if self.freeze_authority_revoked else "⚠️ Can Freeze"

    def holder_badge(self) -> str:
        if not self.available or self.top10_holder_pct is None:
            return "Top10 Holders: N/A"
        return f"Top10 Holders: {self.top10_holder_pct:.1f}%"

    def compact_line(self) -> str:
        if not self.available:
            return "❔ Safety data unavailable"
        return f"{self.mint_badge()} | {self.freeze_badge()} | {self.holder_badge()}"


class SafetyChecker:
    """Async client for RugCheck token safety reports."""

    def __init__(
        self,
        base_url: str = "https://api.rugcheck.xyz/v1",
        timeout: float = 2.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=timeout)

    async def check_token(self, mint: str, use_cache: bool = True) -> TokenSafetyReport:
        """Fetch a token's safety report, degrading gracefully on any failure."""
        if use_cache:
            cached = _safety_cache.get(mint)
            if cached is not None:
                cached_at, cached_report = cached
                if time.monotonic() - cached_at < SAFETY_CACHE_TTL_SECONDS:
                    return cached_report

        report = await self._fetch(mint)
        if use_cache:
            _safety_cache[mint] = (time.monotonic(), report)
        return report

    async def _fetch(self, mint: str) -> TokenSafetyReport:
        try:
            resp = await self.client.get(f"{self.base_url}/tokens/{mint}/report")
            if resp.status_code != 200:
                return TokenSafetyReport(mint=mint, available=False)

            data = resp.json()
            top_holders = data.get("topHolders") or []
            top10_pct = (
                sum(float(h.get("pct", 0.0)) for h in top_holders[:10]) if top_holders else None
            )

            return TokenSafetyReport(
                mint=mint,
                available=True,
                mint_authority_revoked=data.get("mintAuthority") is None,
                freeze_authority_revoked=data.get("freezeAuthority") is None,
                top10_holder_pct=top10_pct,
            )
        except Exception:
            return TokenSafetyReport(mint=mint, available=False)

    async def close(self) -> None:
        await self.client.aclose()
