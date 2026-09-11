"""Unit tests for Telegram Bot formatters and handlers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import bot
from bot import (
    build_welcome_message,
    format_quote_message,
    format_token_radar_message,
)
from core.radar import TokenInfo
from core.router import QuoteResponse


def test_build_welcome_message():
    """Verify welcome message displays fee terms and core commands."""
    msg = build_welcome_message("TestWallet123")
    assert "0.50%" in msg
    assert "Jito MEV" in msg
    assert "/scan" in msg
    assert "/quote" in msg
    assert "TestWa...t123" in msg


def test_format_token_radar_message():
    """Verify token list is formatted clearly for Telegram with volume and liquidity."""
    tokens = [
        TokenInfo(
            mint="DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
            symbol="BONK",
            name="Bonk",
            price_usd=0.000025,
            volume_24h_usd=15000000.0,
            liquidity_usd=5000000.0,
            price_change_5m_pct=1.2,
            dex_id="raydium",
        )
    ]
    text, keyboard = format_token_radar_message(tokens)
    assert "BONK" in text
    assert "$15,000,000" in text
    assert len(keyboard) == 1
    assert "BONK" in keyboard[0][0].text


def test_format_quote_message():
    """Verify quote output shows expected return and 0.50% fee accurately."""
    quote = QuoteResponse(
        input_mint="So11111111111111111111111111111111111111112",
        output_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        in_amount=100_000_000,
        out_amount=10_000_000,
        price_impact_pct=0.01,
        platform_fee_amount=50_000,
    )
    text = format_quote_message(quote, symbol="USDC")
    assert "0.1000 SOL" in text
    assert "10,000,000 USDC" in text
    assert "50,000 USDC units (0.50%)" in text
    assert "Jito MEV Private Engine" in text


@pytest.mark.asyncio
async def test_quote_handler_rejects_invalid_amount():
    """Verify /quote <mint> <bad-amount> replies with a usage error instead
    of raising an unhandled ValueError past the handler -- previously any
    Telegram user typing e.g. `/quote <mint> banana` got silence, since the
    float() parse happened before the try/except."""
    update = MagicMock()
    update.message = AsyncMock()
    context = MagicMock()
    context.args = ["EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "banana"]

    await bot.quote_handler(update, context)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "Invalid amount" in reply_text


@pytest.mark.asyncio
async def test_quote_handler_happy_path():
    """Verify a valid /quote call fetches a quote and replies with the
    formatted result."""
    update = MagicMock()
    update.message = AsyncMock()
    context = MagicMock()
    context.args = ["EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "0.1"]

    fake_quote = QuoteResponse(
        input_mint="So11111111111111111111111111111111111111112",
        output_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        in_amount=100_000_000,
        out_amount=9_900_000,
        price_impact_pct=0.01,
        platform_fee_amount=49_500,
    )

    with patch("bot.JupiterRouter") as mock_router_cls:
        mock_router = mock_router_cls.return_value
        mock_router.get_quote = AsyncMock(return_value=fake_quote)
        mock_router.close = AsyncMock()

        await bot.quote_handler(update, context)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "9,900,000" in reply_text
    assert "49,500" in reply_text
