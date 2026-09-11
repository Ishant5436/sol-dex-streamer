"""Unit tests for the RugCheck token safety client."""

from unittest.mock import AsyncMock, patch

import pytest

from core.safety import SafetyChecker, clear_safety_cache

MINT = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_safety_cache()
    yield
    clear_safety_cache()


@pytest.mark.asyncio
async def test_check_token_parses_report_fields():
    """Verify mintAuthority/freezeAuthority null means revoked, and
    top10_holder_pct sums the first 10 topHolders entries."""
    checker = SafetyChecker()
    mock_resp = {
        "mintAuthority": None,
        "freezeAuthority": "SomeActiveFreezeAuthorityPubkey1111111111",
        "topHolders": [{"pct": 10.0}, {"pct": 5.0}, {"pct": 2.5}],
    }

    with patch.object(checker.client, "get", new_callable=AsyncMock) as mock_get:
        mock_http_response = AsyncMock()
        mock_http_response.status_code = 200
        mock_http_response.json = lambda: mock_resp
        mock_get.return_value = mock_http_response

        report = await checker.check_token(MINT)

    assert report.available
    assert report.mint_authority_revoked is True
    assert report.freeze_authority_revoked is False
    assert report.top10_holder_pct == pytest.approx(17.5)
    assert report.mint_badge() == "✅ Mint Disabled"
    assert report.freeze_badge() == "⚠️ Can Freeze"

    await checker.close()


@pytest.mark.asyncio
async def test_check_token_parses_rugged_and_insider_fields():
    """Verify rugged/insider/risk_score are parsed as-is (not falsy-coerced --
    a real 0 for insider_accounts or risk_score must be preserved, not
    treated as "missing")."""
    checker = SafetyChecker()
    mock_resp = {
        "mintAuthority": None,
        "freezeAuthority": None,
        "topHolders": [],
        "rugged": False,
        "graphInsidersDetected": 0,
        "score_normalised": 0,
    }

    with patch.object(checker.client, "get", new_callable=AsyncMock) as mock_get:
        mock_http_response = AsyncMock()
        mock_http_response.status_code = 200
        mock_http_response.json = lambda: mock_resp
        mock_get.return_value = mock_http_response

        report = await checker.check_token(MINT)

    assert report.rugged is False
    assert report.insider_accounts == 0
    assert report.risk_score == 0
    assert report.rugged_badge() == "✅ Not Flagged as Rugged"
    assert report.insider_badge() == "✅ No insider clusters detected"

    await checker.close()


def test_rugged_badge_omitted_when_unassessed():
    """Verify rugged=None (RugCheck hasn't assessed this token, common for
    brand-new tokens) is shown as unknown, never as a false "clean" result."""
    from core.safety import TokenSafetyReport

    report = TokenSafetyReport(mint=MINT, available=True, rugged=None)
    assert report.rugged_badge() is None
    assert "RUGGED" not in report.compact_line()


def test_rugged_badge_flags_confirmed_rug():
    from core.safety import TokenSafetyReport

    report = TokenSafetyReport(
        mint=MINT,
        available=True,
        rugged=True,
        mint_authority_revoked=True,
        freeze_authority_revoked=True,
        top10_holder_pct=10.0,
    )
    assert report.rugged_badge() == "🚨 FLAGGED AS RUGGED"
    assert "🚨 FLAGGED AS RUGGED" in report.compact_line()
    assert "🚨 FLAGGED AS RUGGED" in report.full_report_text()


@pytest.mark.asyncio
async def test_check_token_degrades_gracefully_on_http_error():
    """Verify a non-200 response never raises -- it degrades to unavailable."""
    checker = SafetyChecker()

    with patch.object(checker.client, "get", new_callable=AsyncMock) as mock_get:
        mock_http_response = AsyncMock()
        mock_http_response.status_code = 500
        mock_get.return_value = mock_http_response

        report = await checker.check_token(MINT)

    assert report.available is False
    assert report.compact_line() == "❔ Safety data unavailable"

    await checker.close()


@pytest.mark.asyncio
async def test_check_token_degrades_gracefully_on_network_exception():
    """Verify a raised exception (timeout, DNS failure, etc.) never
    propagates out of check_token."""
    checker = SafetyChecker()

    with patch.object(checker.client, "get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = TimeoutError("connect timed out")

        report = await checker.check_token(MINT)

    assert report.available is False

    await checker.close()


@pytest.mark.asyncio
async def test_check_token_caches_within_ttl():
    """Verify a second call within the TTL does not re-fetch."""
    checker = SafetyChecker()
    mock_resp = {"mintAuthority": None, "freezeAuthority": None, "topHolders": []}

    with patch.object(checker.client, "get", new_callable=AsyncMock) as mock_get:
        mock_http_response = AsyncMock()
        mock_http_response.status_code = 200
        mock_http_response.json = lambda: mock_resp
        mock_get.return_value = mock_http_response

        await checker.check_token(MINT)
        await checker.check_token(MINT)

        mock_get.assert_called_once()

    await checker.close()
