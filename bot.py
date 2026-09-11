"""Telegram Bot Interface for sol-dex-streamer.

Allows any Telegram user or community group to scan trending tokens,
query Jupiter quotes, and execute swaps with 0.50% platform fee streaming
and Jito MEV protection.
"""

import asyncio
import logging
import os
import re
from typing import Any
from urllib.parse import quote as urlquote

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from core.radar import TokenInfo, TokenRadar
from core.router import JupiterRouter, QuoteRequest, QuoteResponse
from core.safety import SafetyChecker, TokenSafetyReport

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# httpx/httpcore log the full request URL at INFO, and Telegram's Bot API
# embeds the bot token directly in that URL (/bot<TOKEN>/method) -- without
# this, every poll cycle writes the live token to the daemon's log file.
for _noisy_logger in ("httpx", "httpcore"):
    logging.getLogger(_noisy_logger).setLevel(logging.WARNING)

SOL_MINT = "So11111111111111111111111111111111111111112"
DEFAULT_FEE_RECIPIENT = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"

_MARKDOWN_UNSAFE = re.compile(r"[*_`\[\]]")


def sanitize_markdown(text: str) -> str:
    """Strip legacy-Markdown metacharacters from untrusted display text.

    Telegram's parse_mode="Markdown" rejects the entire message on an
    unbalanced *, _, or ` -- token symbol/name come from DexScreener and
    are not trustworthy input.
    """
    return _MARKDOWN_UNSAFE.sub("", text)


def build_swap_links(mint: str) -> tuple[str, str]:
    """Build the desktop Jupiter URL and its Phantom in-app-browser deep link.

    feeBps alone on a jup.ag URL does nothing -- Jupiter's URL-level referral
    fee requires a `referrer` pointing at a Referral Account PDA registered
    via referral.jup.ag (confirmed against Jupiter's docs), which is a
    separate setup step from this project's own ATA-based feeAccount used in
    the bot/CLI's own quote+swap flow. Fee params are only added here once
    that registered PDA is configured; otherwise they're omitted rather than
    shown as if they were already working.
    """
    desktop_url = f"https://jup.ag/swap/SOL-{mint}"
    referral_account = os.environ.get("JUPITER_REFERRAL_ACCOUNT")
    if referral_account:
        desktop_url += f"?referrer={referral_account}&feeBps=50"

    mobile_deep_link = f"https://phantom.app/ul/browse/{urlquote(desktop_url, safe='')}"
    return desktop_url, mobile_deep_link


def build_quick_buy_keyboard(mint: str, symbol: str) -> list[list[InlineKeyboardButton]]:
    """Build the multi-tier quick-buy + 1-click swap button grid for one token."""
    desktop_url, mobile_deep_link = build_swap_links(mint)
    return [
        [
            InlineKeyboardButton(f"{symbol} 0.1 SOL", callback_data=f"quote:{mint}:0.1"),
            InlineKeyboardButton(f"{symbol} 0.5 SOL", callback_data=f"quote:{mint}:0.5"),
        ],
        [
            InlineKeyboardButton(f"{symbol} 1.0 SOL", callback_data=f"quote:{mint}:1.0"),
            InlineKeyboardButton(f"{symbol} 2.0 SOL", callback_data=f"quote:{mint}:2.0"),
        ],
        [InlineKeyboardButton("⚡ 1-Click Swap (Phantom) ↗", url=mobile_deep_link)],
        [InlineKeyboardButton("🖥 Open in Browser (Jupiter) ↗", url=desktop_url)],
    ]


def build_welcome_message(fee_recipient: str) -> str:
    """Build the markdown welcome and instruction message."""
    trunc_acc = (
        fee_recipient[:6] + "..." + fee_recipient[-4:]
        if len(fee_recipient) > 10
        else fee_recipient
    )
    return (
        "⚡ *SOLSHIELD SNIPER* ⚡\n\n"
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
    safety_reports: dict[str, TokenSafetyReport] | None = None,
) -> tuple[str, list[list[InlineKeyboardButton]]]:
    """Format token radar list and generate inline action buttons."""
    safety_reports = safety_reports or {}
    lines = ["🔥 *Trending High-Volume Solana Pairs*\n"]
    keyboard: list[list[InlineKeyboardButton]] = []

    for i, t in enumerate(tokens, 1):
        symbol = sanitize_markdown(t.symbol) or "UNKNOWN"
        name = sanitize_markdown(t.name) or symbol
        trunc_mint = t.mint[:4] + "..." + t.mint[-4:]
        report = safety_reports.get(t.mint)
        safety_line = f"• {report.compact_line()}\n" if report else ""
        lines.append(
            f"*{i}. {symbol}* ({name})\n"
            f"• Price: `${t.price_usd:,.4f}` | 5m: `{t.price_change_5m_pct:+.2f}%`\n"
            f"• 24h Vol: `${t.volume_24h_usd:,.0f}` | Liq: `${t.liquidity_usd:,.0f}`\n"
            f"{safety_line}"
            f"• Mint: `{trunc_mint}`\n"
        )
        keyboard.extend(build_quick_buy_keyboard(t.mint, symbol))

    return "\n".join(lines), keyboard


def format_quote_message(
    quote: QuoteResponse,
    symbol: str = "TOKEN",
    mint: str | None = None,
    safety_report: TokenSafetyReport | None = None,
) -> tuple[str, list[list[InlineKeyboardButton]]]:
    """Format Jupiter quote details for Telegram, with a quick-buy/swap keyboard."""
    symbol = sanitize_markdown(symbol) or "TOKEN"
    sol_amount = quote.in_amount / 1_000_000_000
    fee_str = (
        f"{quote.platform_fee_amount:,} {symbol} units (0.50%)"
        if quote.platform_fee_amount is not None
        else "0.50% requested"
    )
    safety_line = f"• *Safety:* `{safety_report.compact_line()}`\n" if safety_report else ""

    text = (
        "🎯 *Jupiter Swap Quote*\n\n"
        f"• *Pay:* `{sol_amount:.4f} SOL`\n"
        f"• *Receive (Est):* `{quote.out_amount:,} {symbol}`\n"
        f"• *Price Impact:* `{quote.price_impact_pct:.3f}%`\n"
        f"• *Platform Fee (via bot's own swap):* `{fee_str}`\n"
        f"{safety_line}"
        "• *MEV Shield:* `Jito MEV Private Engine Armed` 🛡️\n"
    )

    keyboard = build_quick_buy_keyboard(mint, symbol) if mint else []
    return text, keyboard


def load_dotenv_fallback() -> None:
    """Load environment variables from a local .env file if present."""
    if not os.path.exists(".env"):
        return
    try:
        with open(".env", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip("\"'")
                    if k and k not in os.environ:
                        os.environ[k] = v
    except Exception:
        pass


load_dotenv_fallback()


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start and /help commands."""
    fee_acc = (
        os.environ.get("SOL_FEE_RECIPIENT")
        or os.environ.get("PLATFORM_FEE_WALLET")
        or DEFAULT_FEE_RECIPIENT
    )
    msg = build_welcome_message(fee_acc)
    if update.message:
        await update.message.reply_text(msg, parse_mode="Markdown")


async def scan_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /scan command."""
    if not update.message:
        return

    status_msg = await update.message.reply_text("🔍 Scanning DexScreener & Raydium...")
    radar = TokenRadar(min_liquidity_usd=10000.0, min_volume_24h_usd=25000.0)
    checker = SafetyChecker()
    try:
        tokens = await radar.fetch_trending_tokens(limit=5)
        if not tokens:
            await status_msg.edit_text("⚠️ No tokens passed liquidity filters ($10k+). Try again.")
            return

        reports = await asyncio.gather(*(checker.check_token(t.mint) for t in tokens))
        safety_reports = {t.mint: r for t, r in zip(tokens, reports, strict=True)}

        text, keyboard = format_token_radar_message(tokens, safety_reports)
        reply_markup = InlineKeyboardMarkup(keyboard)
        await status_msg.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Scan error: {e}")
        await status_msg.edit_text(f"❌ Error fetching token radar: {e}")
    finally:
        await radar.close()
        await checker.close()


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
    checker = SafetyChecker()
    try:
        req = QuoteRequest(
            input_mint=SOL_MINT,
            output_mint=mint,
            amount_lamports=amount_lamports,
            slippage_bps=50,
            platform_fee_bps=50,
        )
        quote, safety_report = await asyncio.gather(
            router.get_quote(req), checker.check_token(mint)
        )
        text, keyboard = format_quote_message(quote, mint=mint, safety_report=safety_report)
        swap_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, reply_markup=swap_markup, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Quote error: {e}")
        await update.message.reply_text(f"❌ Error fetching quote: {e}")
    finally:
        await router.close()
        await checker.close()


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
        checker = SafetyChecker()
        try:
            req = QuoteRequest(
                input_mint=SOL_MINT,
                output_mint=mint,
                amount_lamports=amount_lamports,
                slippage_bps=50,
                platform_fee_bps=50,
            )
            quote, safety_report = await asyncio.gather(
                router.get_quote(req), checker.check_token(mint)
            )
            text, keyboard = format_quote_message(quote, mint=mint, safety_report=safety_report)
            swap_markup = InlineKeyboardMarkup(keyboard)
            if query.message:
                await query.message.reply_text(
                    text, reply_markup=swap_markup, parse_mode="Markdown"
                )
        except Exception as e:
            if query.message:
                await query.message.reply_text(f"❌ Error fetching quote: {e}")
        finally:
            await router.close()
            await checker.close()


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
