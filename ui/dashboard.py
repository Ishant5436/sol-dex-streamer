"""Rich ANSI Terminal Dashboard for Solana Token Discovery and Execution."""


from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from core.radar import TokenInfo
from core.router import QuoteResponse

console = Console()


def render_header(
    wallet_pubkey: str | None = None,
    fee_recipient: str | None = None,
) -> Panel:
    """Render system header and wallet telemetry."""
    user_str = (
        f"{wallet_pubkey[:6]}...{wallet_pubkey[-4:]}"
        if wallet_pubkey
        else "Disconnected (Viewing Mode)"
    )
    fee_str = (
        f"{fee_recipient[:6]}...{fee_recipient[-4:]}"
        if fee_recipient
        else "Default Platform Protocol"
    )

    content = Text()
    content.append("⚡ SOL-DEX-STREAMER", style="bold cyan")
    content.append(" | High-Speed Solana DEX Sniper\n", style="bold white")
    content.append(
        f"Trader: {user_str} | Fee: 0.50% (50 bps) | Recipient: {fee_str}\n",
        style="dim",
    )
    content.append(
        "Execution: Jupiter v6 + Jito Private Validator Bundles (Zero Sandwich)",
        style="green",
    )

    return Panel(content, border_style="cyan", padding=(0, 1))


def render_token_table(tokens: list[TokenInfo]) -> Table:
    """Render live trending tokens table."""
    table = Table(
        title="🔥 Live High-Volume Token Radar (DexScreener / Raydium)",
        header_style="bold magenta",
        expand=True,
    )

    table.add_column("#", style="dim", width=4)
    table.add_column("Symbol", style="bold yellow")
    table.add_column("Name", style="white")
    table.add_column("Price (USD)", justify="right", style="cyan")
    table.add_column("5m Change", justify="right")
    table.add_column("24h Volume", justify="right", style="green")
    table.add_column("Liquidity", justify="right", style="blue")
    table.add_column("Mint", style="dim")

    for idx, t in enumerate(tokens, 1):
        change_style = "bold green" if t.price_change_5m_pct >= 0 else "bold red"
        change_str = f"{t.price_change_5m_pct:+.2f}%"

        price_str = f"${t.price_usd:.6f}" if t.price_usd < 1 else f"${t.price_usd:,.2f}"
        vol_str = f"${t.volume_24h_usd:,.0f}"
        liq_str = f"${t.liquidity_usd:,.0f}"
        mint_trunc = f"{t.mint[:4]}...{t.mint[-4:]}"

        table.add_row(
            str(idx),
            t.symbol,
            t.name[:20],
            price_str,
            Text(change_str, style=change_style),
            vol_str,
            liq_str,
            mint_trunc,
        )

    return table


def render_quote_summary(quote: QuoteResponse, symbol: str = "TOKEN") -> Panel:
    """Render quote details and platform fee breakdown.

    Jupiter denominates the platform fee in the swap's *output* mint, not
    SOL -- so it's shown in the same raw-unit form as "Expected Out" rather
    than divided by SOL's lamport factor and mislabeled as SOL.
    """
    sol_amount = quote.in_amount / 1_000_000_000

    text = Text()
    text.append(f"Input:         {sol_amount:.4f} SOL\n", style="bold white")
    text.append(f"Expected Out:  {quote.out_amount:,} {symbol} units\n", style="bold cyan")
    text.append(f"Price Impact:  {quote.price_impact_pct:.3f}%\n", style="yellow")
    if quote.platform_fee_amount is not None:
        text.append(
            f"Platform Fee:  {quote.platform_fee_amount:,} {symbol} units (0.50% of output)\n",
            style="bold green",
        )
    else:
        text.append(
            "Platform Fee:  unavailable from quote (0.50% requested)\n",
            style="bold yellow",
        )
    text.append("MEV Shield:    Jito Bundle Armed (Private block engine)", style="dim green")

    return Panel(
        text, title="🎯 Jupiter Swap Quote", border_style="green", padding=(0, 1)
    )
