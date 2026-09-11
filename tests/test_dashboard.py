"""Unit tests for the terminal dashboard's quote/fee rendering."""

from core.router import QuoteResponse
from ui.dashboard import render_quote_summary


def test_render_quote_summary_shows_fee_in_output_mint_units():
    """Verify the fee line shows Jupiter's raw platformFee.amount as-is,
    labeled with the output token -- not divided by SOL's lamport factor
    and mislabeled "SOL" (confirmed live: a $0.0499 USDC fee rendered as
    "0.0000499 SOL" before this fix)."""
    quote = QuoteResponse(
        input_mint="So11111111111111111111111111111111111111112",
        output_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        in_amount=100_000_000,
        out_amount=9_938_695,
        price_impact_pct=0.0,
        platform_fee_amount=49_943,
    )

    rendered = render_quote_summary(quote, symbol="USDC").renderable.plain

    assert "49,943 USDC units" in rendered
    assert "0.0000499 SOL" not in rendered
    assert "0.000050 SOL" not in rendered


def test_render_quote_summary_handles_missing_fee_honestly():
    """Verify a missing platformFee is reported as unavailable rather than
    guessed from the input amount."""
    quote = QuoteResponse(
        input_mint="So11111111111111111111111111111111111111112",
        output_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        in_amount=100_000_000,
        out_amount=9_938_695,
        price_impact_pct=0.0,
        platform_fee_amount=None,
    )

    rendered = render_quote_summary(quote, symbol="USDC").renderable.plain

    assert "unavailable" in rendered
