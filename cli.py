#!/usr/bin/env python3
"""CLI Entry Point for Solana DEX Streamer & MEV Sniper."""

import argparse
import asyncio
import os

from core.executor import JitoBundler, fetch_recent_blockhash, load_keypair
from core.radar import TokenRadar
from core.router import JupiterRouter, QuoteRequest, SwapRequest, derive_fee_token_account
from ui.dashboard import console, render_header, render_quote_summary, render_token_table

SOL_MINT = "So11111111111111111111111111111111111111112"
DEFAULT_FEE_RECIPIENT = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"


async def run_scan(limit: int = 10):
    """Scan and display high-volume tokens."""
    radar = TokenRadar()
    try:
        console.print(render_header())
        with console.status("[bold cyan]Scanning DexScreener & Raydium streams..."):
            tokens = await radar.fetch_trending_tokens(limit=limit)

        if not tokens:
            console.print("[yellow]No tokens passed liquidity filter ($10k+). Retrying...[/yellow]")
            return

        console.print(render_token_table(tokens))
    finally:
        await radar.close()


async def run_quote(output_mint: str, amount_sol: float, fee_recipient: str | None = None):
    """Fetch and display Jupiter quote with 0.50% fee."""
    router = JupiterRouter()
    fee_acc = fee_recipient or os.environ.get("SOL_FEE_RECIPIENT", DEFAULT_FEE_RECIPIENT)
    amount_lamports = int(amount_sol * 1_000_000_000)

    try:
        console.print(render_header(fee_recipient=fee_acc))
        with console.status(
            f"[bold cyan]Fetching quote for {amount_sol} SOL -> {output_mint[:8]}..."
        ):
            req = QuoteRequest(
                input_mint=SOL_MINT,
                output_mint=output_mint,
                amount_lamports=amount_lamports,
                slippage_bps=50,
                platform_fee_bps=50,
            )
            quote = await router.get_quote(req)

        console.print(render_quote_summary(quote))
        return quote
    finally:
        await router.close()


async def run_swap(
    output_mint: str,
    amount_sol: float,
    dry_run: bool = True,
    fee_recipient: str | None = None,
):
    """Fetch quote, construct swap transaction, and dispatch via Jito MEV bundle."""
    router = JupiterRouter()
    bundler = JitoBundler()
    fee_acc = fee_recipient or os.environ.get("SOL_FEE_RECIPIENT", DEFAULT_FEE_RECIPIENT)
    amount_lamports = int(amount_sol * 1_000_000_000)

    try:
        console.print(render_header(fee_recipient=fee_acc))
        with console.status(f"[bold cyan]Step 1/3: Getting Quote for {amount_sol} SOL..."):
            q_req = QuoteRequest(
                input_mint=SOL_MINT,
                output_mint=output_mint,
                amount_lamports=amount_lamports,
                slippage_bps=50,
                platform_fee_bps=50,
            )
            # use_cache=False: this quote feeds directly into a swap transaction
            # in live mode, so a stale cached quote would build against outdated
            # pricing/liquidity.
            quote = await router.get_quote(q_req, use_cache=False)

        console.print(render_quote_summary(quote))

        if dry_run:
            console.print(
                "[bold yellow]⚡ DRY-RUN MODE: Quote retrieved. "
                "Transaction execution skipped.[/bold yellow]"
            )
            return

        # Live Execution
        payer = load_keypair()
        fee_token_account = derive_fee_token_account(fee_acc, output_mint)
        with console.status("[bold cyan]Step 2/3: Constructing Jupiter Transaction..."):
            s_req = SwapRequest(
                quote_response=quote.raw_data,
                user_public_key=str(payer.pubkey()),
                fee_account=fee_token_account,
                dynamic_compute_unit_limit=True,
            )
            tx_b64 = await router.get_swap_transaction(s_req)

        with console.status("[bold cyan]Step 3/3: Packing Jito MEV Bundle..."):
            signed_tx = bundler.sign_jupiter_transaction(tx_b64, payer)
            recent_blockhash = await fetch_recent_blockhash(
                os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
            )
            tip_tx = bundler.create_tip_transaction(
                payer, tip_lamports=10000, recent_blockhash=recent_blockhash
            )

            import base58

            b58_swap = base58.b58encode(bytes(signed_tx)).decode("utf-8")
            b58_tip = base58.b58encode(bytes(tip_tx)).decode("utf-8")

            bundle_id = await bundler.send_bundle([b58_swap, b58_tip])
            console.print(
                f"[bold green]🚀 Jito MEV Bundle Dispatched! Bundle ID: {bundle_id}[/bold green]"
            )

    finally:
        await router.close()
        await bundler.close()


def main():
    parser = argparse.ArgumentParser(
        description="SOL-DEX-STREAMER: High-Speed Solana Sniper & 0.50% Fee Streamer"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # scan
    scan_p = subparsers.add_parser("scan", help="Scan live high-volume tokens")
    scan_p.add_argument("--limit", type=int, default=10, help="Number of tokens to display")

    # quote
    quote_p = subparsers.add_parser("quote", help="Get Jupiter v6 quote with 50 bps fee")
    quote_p.add_argument("--token", required=True, help="Output token mint address")
    quote_p.add_argument("--amount", type=float, default=0.1, help="SOL amount to swap")
    quote_p.add_argument("--fee-recipient", type=str, default=None, help="Fee recipient pubkey")

    # swap
    swap_p = subparsers.add_parser("swap", help="Execute swap with Jito MEV protection")
    swap_p.add_argument("--token", required=True, help="Output token mint address")
    swap_p.add_argument("--amount", type=float, default=0.1, help="SOL amount to swap")
    swap_p.add_argument("--live", action="store_true", help="Execute live transaction")
    swap_p.add_argument("--fee-recipient", type=str, default=None, help="Fee recipient pubkey")

    # bot
    bot_p = subparsers.add_parser("bot", help="Run Telegram bot daemon")
    bot_p.add_argument("--token", type=str, default=None, help="Telegram Bot Token")

    args = parser.parse_args()

    if args.command == "scan":
        asyncio.run(run_scan(limit=args.limit))
    elif args.command == "quote":
        asyncio.run(
            run_quote(
                output_mint=args.token,
                amount_sol=args.amount,
                fee_recipient=args.fee_recipient,
            )
        )
    elif args.command == "swap":
        asyncio.run(
            run_swap(
                output_mint=args.token,
                amount_sol=args.amount,
                dry_run=(not args.live),
                fee_recipient=args.fee_recipient,
            )
        )
    elif args.command == "bot":
        from bot import build_telegram_app

        tg_token = args.token or os.environ.get("TELEGRAM_BOT_TOKEN")
        if not tg_token:
            console.print(
                "[bold red]Error:[/bold red] TELEGRAM_BOT_TOKEN is required. "
                "Provide --token or export TELEGRAM_BOT_TOKEN."
            )
            return
        console.print("[bold green]🤖 Starting Telegram Bot polling daemon...[/bold green]")
        app = build_telegram_app(tg_token)
        app.run_polling()


if __name__ == "__main__":
    main()
