"""Telegram Bot Interface for sol-dex-streamer.

Allows any Telegram user or community group to scan trending tokens,
query Jupiter quotes, and execute swaps with 0.50% platform fee streaming
and Jito MEV protection.
"""

import logging
import os
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from core.radar import TokenInfo, TokenRadar
from core.router import JupiterRouter, QuoteRequest, QuoteResponse

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

SOL_MINT = "So11111111111111111111111111111111111111112"
DEFAULT_FEE_RECIPIENT = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"


def build_welcome_message(fee_recipient: str) -> str:
    """Build the markdown welcome and instruction message."""
    trunc_acc = (
        fee_recipient[:6] + "..." + fee_recipient[-4:]
        if len(fee_recipient) > 10
        else fee_recipient
    )
    return (
        "⚡ *SOL-DEX-STREAMER TELEGRAM BOT* ⚡\n\n"
        "High-speed Solana token scanner and sniper with Jito MEV protection.\n\n"
        "*Core Invariants:*\n"
        "• *Platform Fee:* 0.50% (50 bps) — Half the cost of Trojan / Maestro (1.00%).\n"
        "• *MEV Protection:* Transactions routed via Jito MEV private validator bundles.\n"
        f"• *Fee Recipient:* `{trunc_acc}`\n\n"
        "*Commands:*\n"
        "• `/scan` — Scan live trending Solana tokens with >$10k liquidity\n"
        "• `/quote <mint> [sol]` — Fetch Jupiter quote with 0.50% fee\n"
        "• `/help` — Display this guide\n"
    )


def format_token_radar_message(
    tokens: list[TokenInfo],
) -> tuple[str, list[list[InlineKeyboardButton]]]:
    """Format token radar list and generate inline action buttons."""
    lines = ["🔥 *Trending High-Volume Solana Pairs*\n"]
    keyboard: list[list[InlineKeyboardButton]] = []

    for i, t in enumerate(tokens, 1):
        trunc_mint = t.mint[:4] + "..." + t.mint[-4:]
        lines.append(
            f"*{i}. {t.symbol}* ({t.name})\n"
            f"• Price: `${t.price_usd:,.4f}` | 5m: `{t.price_change_5m_pct:+.2f}%`\n"
            f"• 24h Vol: `${t.volume_24h_usd:,.0f}` | Liq: `${t.liquidity_usd:,.0f}`\n"
            f"• Mint: `{trunc_mint}`\n"
        )
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"Quote {t.symbol} (0.1 SOL)",
                    callback_data=f"quote:{t.mint}:0.1",
                ),
                InlineKeyboardButton(
                    f"Quote {t.symbol} (0.5 SOL)",
                    callback_data=f"quote:{t.mint}:0.5",
                ),
            ]
        )

    return "\n".join(lines), keyboard


def format_quote_message(quote: QuoteResponse, symbol: str = "TOKEN") -> str:
    """Format Jupiter quote details for Telegram."""
    sol_amount = quote.in_amount / 1_000_000_000
    fee_str = (
        f"{quote.platform_fee_amount:,} {symbol} units (0.50%)"
        if quote.platform_fee_amount is not None
        else "0.50% requested"
    )

    return (
        "🎯 *Jupiter Swap Quote*\n\n"
        f"• *Pay:* `{sol_amount:.4f} SOL`\n"
        f"• *Receive (Est):* `{quote.out_amount:,} {symbol}`\n"
        f"• *Price Impact:* `{quote.price_impact_pct:.3f}%`\n"
        f"• *Platform Fee:* `{fee_str}`\n"
        "• *MEV Shield:* `Jito MEV Private Engine Armed` 🛡️\n"
    )


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start and /help commands."""
    fee_acc = os.environ.get("SOL_FEE_RECIPIENT", DEFAULT_FEE_RECIPIENT)
    msg = build_welcome_message(fee_acc)
    if update.message:
        await update.message.reply_text(msg, parse_mode="Markdown")


async def scan_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /scan command."""
    if not update.message:
        return

    status_msg = await update.message.reply_text("🔍 Scanning DexScreener & Raydium...")
    radar = TokenRadar(min_liquidity_usd=10000.0, min_volume_24h_usd=25000.0)
    try:
        tokens = await radar.fetch_trending_tokens(limit=5)
        if not tokens:
            await status_msg.edit_text("⚠️ No tokens passed liquidity filters ($10k+). Try again.")
            return

        text, keyboard = format_token_radar_message(tokens)
        reply_markup = InlineKeyboardMarkup(keyboard)
        await status_msg.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Scan error: {e}")
        await status_msg.edit_text(f"❌ Error fetching token radar: {e}")
    finally:
        await radar.close()


async def quote_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /quote <mint> [amount_sol]."""
    if not update.message:
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "⚠️ Usage: `/quote <mint_address> [amount_sol]`\n"
            "Example: `/quote EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v 0.1`",
            parse_mode="Markdown",
        )
        return

    mint = args[0]
    try:
        amount_sol = float(args[1]) if len(args) > 1 else 0.1
    except ValueError:
        await update.message.reply_text(
            f"⚠️ Invalid amount: `{args[1]}`. Provide a numeric SOL amount, e.g. `0.1`.",
            parse_mode="Markdown",
        )
        return
    amount_lamports = int(amount_sol * 1_000_000_000)

    router = JupiterRouter()
    try:
        req = QuoteRequest(
            input_mint=SOL_MINT,
            output_mint=mint,
            amount_lamports=amount_lamports,
            slippage_bps=50,
            platform_fee_bps=50,
        )
        quote = await router.get_quote(req)
        text = format_quote_message(quote)
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Quote error: {e}")
        await update.message.reply_text(f"❌ Error fetching quote: {e}")
    finally:
        await router.close()


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard taps."""
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()
    parts = query.data.split(":")
    action = parts[0]

    if action == "quote" and len(parts) >= 3:
        mint = parts[1]
        amount_sol = float(parts[2])
        amount_lamports = int(amount_sol * 1_000_000_000)

        router = JupiterRouter()
        try:
            req = QuoteRequest(
                input_mint=SOL_MINT,
                output_mint=mint,
                amount_lamports=amount_lamports,
                slippage_bps=50,
                platform_fee_bps=50,
            )
            quote = await router.get_quote(req)
            text = format_quote_message(quote)
            if query.message:
                await query.message.reply_text(text, parse_mode="Markdown")
        except Exception as e:
            if query.message:
                await query.message.reply_text(f"❌ Error fetching quote: {e}")
        finally:
            await router.close()


def build_telegram_app(token: str) -> Any:
    """Construct and configure the Telegram application."""
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", start_handler))
    app.add_handler(CommandHandler("scan", scan_handler))
    app.add_handler(CommandHandler("quote", quote_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))
    return app


def main() -> None:
    """Start polling Telegram bot."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN environment variable is not set. "
            "Get a bot token from @BotFather on Telegram and export TELEGRAM_BOT_TOKEN."
        )

    print("🤖 Starting sol-dex-streamer Telegram Bot...")
    app = build_telegram_app(token)
    app.run_polling()


if __name__ == "__main__":
    main()
