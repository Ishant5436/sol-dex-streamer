"""Unit tests for Telegram Bot formatters and handlers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import bot
from bot import (
    build_quick_buy_keyboard,
    build_swap_links,
    build_welcome_message,
    format_quote_message,
    format_token_radar_message,
    sanitize_markdown,
)
from core.radar import TokenInfo
from core.router import QuoteResponse
from core.safety import TokenSafetyReport


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
    # 4-row quick-buy grid per token: [0.1/0.5], [1.0/2.0], [phantom], [browser]
    assert len(keyboard) == 4
    assert "BONK" in keyboard[0][0].text


def test_format_token_radar_message_sanitizes_hostile_symbol():
    """Verify a token symbol/name containing Markdown metacharacters cannot
    break the message's parse_mode="Markdown" rendering."""
    tokens = [
        TokenInfo(
            mint="DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
            symbol="Pump*Fun_",
            name="[Evil](http://x) `token`",
            price_usd=0.01,
            volume_24h_usd=100000.0,
            liquidity_usd=50000.0,
        )
    ]
    text, _ = format_token_radar_message(tokens)
    assert "*Fun_" not in text
    assert "[Evil]" not in text
    assert "`token`" not in text


def test_format_token_radar_message_includes_safety_badges():
    """Verify a supplied TokenSafetyReport's compact badges are rendered."""
    mint = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
    tokens = [
        TokenInfo(
            mint=mint,
            symbol="BONK",
            name="Bonk",
            liquidity_usd=50000.0,
            volume_24h_usd=100000.0,
        )
    ]
    report = TokenSafetyReport(
        mint=mint,
        available=True,
        mint_authority_revoked=True,
        freeze_authority_revoked=False,
        top10_holder_pct=42.5,
    )
    text, _ = format_token_radar_message(tokens, safety_reports={mint: report})
    assert "✅ Mint Disabled" in text
    assert "⚠️ Can Freeze" in text
    assert "42.5%" in text


def test_format_quote_message():
    """Verify quote output shows expected return and 0.50% fee accurately,
    and returns a quick-buy/swap keyboard alongside the text."""
    quote = QuoteResponse(
        input_mint="So11111111111111111111111111111111111111112",
        output_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        in_amount=100_000_000,
        out_amount=10_000_000,
        price_impact_pct=0.01,
        platform_fee_amount=50_000,
    )
    text, keyboard = format_quote_message(
        quote, symbol="USDC", mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    )
    assert "0.1000 SOL" in text
    assert "10,000,000 USDC" in text
    assert "50,000 USDC units (0.50%)" in text
    assert "Jito MEV Private Engine" in text
    assert len(keyboard) == 4


def test_sanitize_markdown_strips_metacharacters():
    assert sanitize_markdown("Pump*Fun_") == "PumpFun"
    assert sanitize_markdown("[link](url)") == "link(url)"
    assert sanitize_markdown("`code`") == "code"
    assert sanitize_markdown("NORMAL") == "NORMAL"


def test_build_swap_links_omits_fee_params_when_unconfigured(monkeypatch):
    """Verify no referrer/feeBps is added unless a registered Jupiter
    Referral Account PDA is configured -- feeBps alone on a jup.ag URL is a
    no-op (confirmed against Jupiter's docs), so showing it unconditionally
    would misrepresent the deep link as fee-collecting when it isn't."""
    monkeypatch.delenv("JUPITER_REFERRAL_ACCOUNT", raising=False)
    mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

    desktop_url, mobile_link = build_swap_links(mint)

    assert desktop_url == f"https://jup.ag/swap/SOL-{mint}"
    assert "feeBps" not in desktop_url
    assert "referrer" not in desktop_url
    assert mobile_link.startswith("https://phantom.app/ul/browse/")
    assert desktop_url.replace(":", "%3A").replace("/", "%2F") in mobile_link


def test_build_swap_links_includes_fee_params_when_configured(monkeypatch):
    """Verify the referrer/feeBps params ARE added once a registered
    Referral Account is configured."""
    monkeypatch.setenv("JUPITER_REFERRAL_ACCOUNT", "SomeRegisteredReferralPda1111111111111111")
    mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

    desktop_url, _ = build_swap_links(mint)

    assert "referrer=SomeRegisteredReferralPda1111111111111111" in desktop_url
    assert "feeBps=50" in desktop_url


@pytest.mark.asyncio
async def test_check_handler_requires_mint_argument():
    """Verify /check with no args replies with usage instead of erroring."""
    update = MagicMock()
    update.message = AsyncMock()
    context = MagicMock()
    context.args = []

    await bot.check_handler(update, context)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "Usage" in reply_text


@pytest.mark.asyncio
async def test_check_handler_happy_path():
    """Verify /check <mint> fetches a safety report and replies with it,
    without requiring any trade amount."""
    update = MagicMock()
    update.message = AsyncMock()
    context = MagicMock()
    mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    context.args = [mint]

    fake_report = TokenSafetyReport(
        mint=mint,
        available=True,
        rugged=False,
        mint_authority_revoked=False,
        freeze_authority_revoked=False,
        top10_holder_pct=12.3,
    )

    with patch("bot.SafetyChecker") as mock_checker_cls:
        mock_checker = mock_checker_cls.return_value
        mock_checker.check_token = AsyncMock(return_value=fake_report)
        mock_checker.close = AsyncMock()

        await bot.check_handler(update, context)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "Safety Report" in reply_text
    assert "⚠️ Mint Active" in reply_text
    assert "12.3%" in reply_text


def test_quick_buy_callback_data_within_telegram_limit():
    """Telegram rejects callback_data over 64 bytes with a BadRequest that
    would surface as a swallowed generic error -- verify every quick-buy
    button stays under that limit even for a max-length mint address."""
    max_len_mint = "A" * 44  # longest realistic base58 Solana address
    keyboard = build_quick_buy_keyboard(max_len_mint, "SYMBOL")

    for row in keyboard:
        for button in row:
            if button.callback_data:
                assert len(button.callback_data.encode("utf-8")) <= 64


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

    fake_report = TokenSafetyReport(mint="mint", available=False)

    with (
        patch("bot.JupiterRouter") as mock_router_cls,
        patch("bot.SafetyChecker") as mock_checker_cls,
    ):
        mock_router = mock_router_cls.return_value
        mock_router.get_quote = AsyncMock(return_value=fake_quote)
        mock_router.close = AsyncMock()
        mock_checker = mock_checker_cls.return_value
        mock_checker.check_token = AsyncMock(return_value=fake_report)
        mock_checker.close = AsyncMock()

        await bot.quote_handler(update, context)

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "9,900,000" in reply_text
    assert "49,500" in reply_text
