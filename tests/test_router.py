"""Unit tests for Jupiter v6 Fee Router."""

from unittest.mock import AsyncMock, patch

import pytest

from core.router import (
    JupiterRouter,
    QuoteRequest,
    SwapRequest,
    clear_quote_cache,
    derive_fee_token_account,
)

SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
MOCK_USER_PUBKEY = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"
MOCK_FEE_PUBKEY = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"


@pytest.fixture(autouse=True)
def _clear_quote_cache():
    """The quote cache is module-level (shared across router instances), so
    it must be reset between tests to avoid one test's cached response
    leaking into another's assertions."""
    clear_quote_cache()
    yield
    clear_quote_cache()


@pytest.mark.asyncio
async def test_get_quote_includes_platform_fee_bps():
    """Verify that get_quote dispatches request with platformFeeBps=50."""
    router = JupiterRouter()

    mock_resp = {
        "inputMint": SOL_MINT,
        "inAmount": "1000000000",
        "outputMint": USDC_MINT,
        "outAmount": "180000000",
        "priceImpactPct": "0.02",
        "platformFee": {
            "amount": "900000",
            "feeBps": 50
        }
    }

    with patch.object(router.client, "get", new_callable=AsyncMock) as mock_get:
        mock_http_response = AsyncMock()
        mock_http_response.status_code = 200
        mock_http_response.json = lambda: mock_resp
        mock_get.return_value = mock_http_response

        req = QuoteRequest(
            input_mint=SOL_MINT,
            output_mint=USDC_MINT,
            amount_lamports=1_000_000_000,
            slippage_bps=50,
            platform_fee_bps=50,
        )

        quote = await router.get_quote(req)

        mock_get.assert_called_once()
        params = mock_get.call_args[1]["params"]
        assert params["platformFeeBps"] == 50
        assert params["inputMint"] == SOL_MINT
        assert params["outputMint"] == USDC_MINT
        assert params["amount"] == 1_000_000_000

        assert quote.in_amount == 1_000_000_000
        assert quote.out_amount == 180_000_000
        assert quote.platform_fee_amount == 900_000

    await router.close()


@pytest.mark.asyncio
async def test_get_swap_transaction_includes_fee_account():
    """Verify that get_swap_transaction dispatches request with feeAccount."""
    router = JupiterRouter()

    mock_swap_resp = {
        "swapTransaction": "AQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA...",
        "lastValidBlockHeight": 250000000
    }

    with patch.object(router.client, "post", new_callable=AsyncMock) as mock_post:
        mock_http_response = AsyncMock()
        mock_http_response.status_code = 200
        mock_http_response.json = lambda: mock_swap_resp
        mock_post.return_value = mock_http_response

        req = SwapRequest(
            quote_response={"mock": "data"},
            user_public_key=MOCK_USER_PUBKEY,
            fee_account=MOCK_FEE_PUBKEY,
            dynamic_compute_unit_limit=True,
        )

        tx_base64 = await router.get_swap_transaction(req)

        mock_post.assert_called_once()
        body = mock_post.call_args[1]["json"]
        assert body["userPublicKey"] == MOCK_USER_PUBKEY
        assert body["feeAccount"] == MOCK_FEE_PUBKEY
        assert body["dynamicComputeUnitLimit"] is True
        assert tx_base64 == mock_swap_resp["swapTransaction"]

    await router.close()


@pytest.mark.asyncio
async def test_get_quote_caches_repeated_requests():
    """Verify a second identical quote request within the TTL is served
    from cache without a second HTTP call -- this is what makes rapid
    repeat taps on the same amount respond instantly."""
    router = JupiterRouter()
    mock_resp = {
        "inputMint": SOL_MINT,
        "inAmount": "1000000000",
        "outputMint": USDC_MINT,
        "outAmount": "180000000",
        "priceImpactPct": "0.02",
        "platformFee": {"amount": "900000", "feeBps": 50},
    }

    with patch.object(router.client, "get", new_callable=AsyncMock) as mock_get:
        mock_http_response = AsyncMock()
        mock_http_response.status_code = 200
        mock_http_response.json = lambda: mock_resp
        mock_get.return_value = mock_http_response

        req = QuoteRequest(
            input_mint=SOL_MINT,
            output_mint=USDC_MINT,
            amount_lamports=1_000_000_000,
            slippage_bps=50,
            platform_fee_bps=50,
        )

        first = await router.get_quote(req)
        second = await router.get_quote(req)

        mock_get.assert_called_once()
        assert first == second

    await router.close()


@pytest.mark.asyncio
async def test_get_quote_use_cache_false_always_refetches():
    """Verify use_cache=False (the run_swap path) always hits the network,
    even for a request identical to a just-cached one -- a stale quote fed
    into a live swap risks building against outdated pricing/liquidity."""
    router = JupiterRouter()
    mock_resp = {
        "inputMint": SOL_MINT,
        "inAmount": "1000000000",
        "outputMint": USDC_MINT,
        "outAmount": "180000000",
        "priceImpactPct": "0.02",
        "platformFee": {"amount": "900000", "feeBps": 50},
    }

    with patch.object(router.client, "get", new_callable=AsyncMock) as mock_get:
        mock_http_response = AsyncMock()
        mock_http_response.status_code = 200
        mock_http_response.json = lambda: mock_resp
        mock_get.return_value = mock_http_response

        req = QuoteRequest(
            input_mint=SOL_MINT,
            output_mint=USDC_MINT,
            amount_lamports=1_000_000_000,
            slippage_bps=50,
            platform_fee_bps=50,
        )

        await router.get_quote(req, use_cache=False)
        await router.get_quote(req, use_cache=False)

        assert mock_get.call_count == 2

    await router.close()


def test_derive_fee_token_account_matches_known_ata():
    """Verify derive_fee_token_account produces the real Associated Token
    Account -- passing the raw wallet address as feeAccount instead fails
    Jupiter's on-chain fee transfer (confirmed live against api.jup.ag)."""
    fee_token_account = derive_fee_token_account(MOCK_FEE_PUBKEY, USDC_MINT)

    assert fee_token_account == "C4PRXFV6Gf5mytVZb6RoeLsG8CjcFWzR2EJ3dvwPTUJH"
    assert fee_token_account != MOCK_FEE_PUBKEY


@pytest.mark.asyncio
async def test_get_quote_http_error_handling():
    """Verify router raises RuntimeError on failed API response."""
    router = JupiterRouter()

    with patch.object(router.client, "get", new_callable=AsyncMock) as mock_get:
        mock_http_response = AsyncMock()
        mock_http_response.status_code = 400
        mock_http_response.text = "TOKEN_NOT_TRADABLE"
        mock_get.return_value = mock_http_response

        req = QuoteRequest(
            input_mint=SOL_MINT,
            output_mint=USDC_MINT,
            amount_lamports=1_000_000,
        )

        with pytest.raises(RuntimeError, match="Jupiter quote failed"):
            await router.get_quote(req)

    await router.close()
