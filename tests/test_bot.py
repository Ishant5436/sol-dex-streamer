"""Unit tests for Telegram Bot formatters and handlers."""

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
