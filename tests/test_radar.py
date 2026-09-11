"""Unit tests for Token Discovery Radar."""

from unittest.mock import AsyncMock, patch

import pytest

from core.radar import TokenInfo, TokenRadar


def _mock_dexscreener_pairs():
    return [
        {
            "baseToken": {
                "address": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
                "name": "Bonk",
                "symbol": "BONK",
            },
            "priceUsd": "0.0000215",
            "volume": {"h24": 1500000.0},
            "liquidity": {"usd": 500000.0},
            "priceChange": {"m5": 2.45},
            "dexId": "raydium",
        },
        {
            "baseToken": {
                "address": "LowLiqToken111111111111111111111111111111111",
                "name": "ScamLowLiq",
                "symbol": "LOW",
            },
            "priceUsd": "0.001",
            "volume": {"h24": 500.0},
            "liquidity": {"usd": 1500.0},  # Below 10k threshold
            "priceChange": {"m5": -50.0},
            "dexId": "raydium",
        },
        {
            "baseToken": {
                "address": "WIFToken111111111111111111111111111111111111",
                "name": "Dogwifhat",
                "symbol": "WIF",
            },
            "priceUsd": "1.85",
            "volume": {"h24": 8000000.0},
            "liquidity": {"usd": 2500000.0},
            "priceChange": {"m5": 0.85},
            "dexId": "raydium",
        },
    ]


@pytest.mark.asyncio
async def test_radar_filters_low_liquidity():
    """Verify radar discards tokens with liquidity below threshold."""
    radar = TokenRadar(min_liquidity_usd=10000.0, min_volume_24h_usd=25000.0)

    filtered = radar.filter_tokens(_mock_dexscreener_pairs())

    assert len(filtered) == 2
    symbols = [t.symbol for t in filtered]
    assert "BONK" in symbols
    assert "WIF" in symbols
    assert "LOW" not in symbols

    await radar.close()


@pytest.mark.asyncio
async def test_fetch_trending_tokens_mocked_http():
    """Verify fetch_trending_tokens parses HTTP API response into TokenInfo objects."""
    radar = TokenRadar()

    with patch.object(radar.client, "get", new_callable=AsyncMock) as mock_get:
        mock_http_response = AsyncMock()
        mock_http_response.status_code = 200
        mock_http_response.json = lambda: _mock_dexscreener_pairs()
        mock_get.return_value = mock_http_response

        tokens = await radar.fetch_trending_tokens(limit=5)

        assert len(tokens) == 2
        assert isinstance(tokens[0], TokenInfo)
        assert tokens[0].symbol == "BONK"
        assert tokens[0].price_usd == 0.0000215
        assert tokens[0].volume_24h_usd == 1500000.0

    await radar.close()


@pytest.mark.asyncio
async def test_fetch_trending_handles_empty_or_error():
    """Verify radar handles API errors gracefully by returning an empty list."""
    radar = TokenRadar()

    with patch.object(radar.client, "get", new_callable=AsyncMock) as mock_get:
        mock_http_response = AsyncMock()
        mock_http_response.status_code = 500
        mock_get.return_value = mock_http_response

        tokens = await radar.fetch_trending_tokens(limit=5)
        assert tokens == []

    await radar.close()
