"""Token Safety and Anti-Rug Audit Client.

Queries RugCheck for mint/freeze authority status, holder concentration,
the explicit `rugged` flag, and insider-cluster graph analysis, so traders
see a rug-risk signal before acting on a scan, quote, or /check.

Uses the full `/report` endpoint, not `/report/summary` -- the summary
response only carries an aggregate risk score and a sparse `risks` list; it
does not expose `mintAuthority`, `freezeAuthority`, or `topHolders` at all
(confirmed live against api.rugcheck.xyz).

Note: RugCheck's `creatorTokens` field (other tokens by the same deployer,
which would enable a "serial rugger" check) came back null/absent for every
token tested here, including established ones -- it isn't reliably
populated via this endpoint, so it's deliberately not used. `rugged` and
the insider-network fields have the same caveat for brand-new tokens (the
population where a safety check matters most): RugCheck's deeper analysis
often hasn't run on them yet, which is why every signal here is `None`
(shown as unknown) rather than a false "clean" result when absent.
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
    rugged: bool | None = None
    insider_accounts: int | None = None
    risk_score: int | None = None

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

    def rugged_badge(self) -> str | None:
        """None means RugCheck hasn't assessed this yet -- distinct from a
        confirmed "not rugged" (False). Only meaningful once populated, which
        in practice is common for newer/smaller tokens -- the exact
        population where this signal matters most, and where it's least
        likely to be available yet."""
        if not self.available or self.rugged is None:
            return None
        return "🚨 FLAGGED AS RUGGED" if self.rugged else "✅ Not Flagged as Rugged"

    def insider_badge(self) -> str | None:
        """None when RugCheck's insider-cluster graph analysis hasn't run for
        this token yet (also common for newer tokens) -- omitted rather than
        shown as a false "clean" result."""
        if not self.available or self.insider_accounts is None:
            return None
        if self.insider_accounts == 0:
            return "✅ No insider clusters detected"
        return f"⚠️ {self.insider_accounts:,} insider-linked accounts"

    def compact_line(self) -> str:
        """Short one-liner for /scan, where up to 5 tokens are listed at once."""
        if not self.available:
            return "❔ Safety data unavailable"
        rugged = self.rugged_badge()
        prefix = f"{rugged} | " if rugged and self.rugged else ""
        return f"{prefix}{self.mint_badge()} | {self.freeze_badge()} | {self.holder_badge()}"

    def full_report_text(self) -> str:
        """Multi-line report for the dedicated /check command, where a
        single token gets the full page rather than a scan-list row."""
        if not self.available:
            return (
                "❔ Safety data unavailable for this mint "
                "(RugCheck unreachable or unknown token)."
            )

        lines = [self.rugged_badge(), self.mint_badge(), self.freeze_badge(), self.holder_badge()]
        insider = self.insider_badge()
        if insider:
            lines.append(insider)
        if self.risk_score is not None:
            lines.append(f"RugCheck Risk Score: {self.risk_score} (lower is safer)")
        return "\n".join(f"• {line}" for line in lines if line)


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
                rugged=data.get("rugged"),
                insider_accounts=data.get("graphInsidersDetected"),
                risk_score=data.get("score_normalised"),
            )
        except Exception:
            return TokenSafetyReport(mint=mint, available=False)

    async def close(self) -> None:
        await self.client.aclose()
