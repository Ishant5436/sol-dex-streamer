# sol-dex-streamer

High-Speed Solana Terminal DEX Router & MEV-Protected Token Sniper with automated 0.50% platform fee streaming.

## Highlights
- **Strictly $0.00 Developer Capital:** End users pay 100% of network fees and gas; a 0.50% (50 bps) platform fee streams directly to your configured wallet on every swap.
- **Jupiter Swap Routing:** Native integration with Jupiter Swap API (`https://api.jup.ag/swap/v1`) with `platformFeeBps: 50`.
- **Jito MEV Shield:** Bundles swaps with validator tips dispatched to Jito Block Engine endpoints, bypassing public mempools to eliminate sandwich attacks.
- **Real-Time Token Radar:** Filters DexScreener/Raydium pairs (Solana-only) with customizable liquidity ($10k+) and volume ($25k+) thresholds.
- **Telegram Bot:** `/scan` and `/quote` from any chat, with inline one-tap quote buttons. Quote-only — no wallet or signing key is reachable from Telegram.
- **High Performance:** Built on `solders` (Rust Python bindings) and `rich` TUI. Lint-clean with `ruff`; `pytest` suite covers 71% of lines overall (92-95% on the core Jupiter/Jito/radar logic, lighter on the UI/bot presentation layers). Run `pytest tests/ --cov=core --cov=ui --cov=bot --cov-report=term-missing` to reproduce.

## Quick Start

### 1. Environment Setup
```bash
# Clone and enter directory
cd /Users/ishantpanchal/sol-dex-streamer

# Activate virtual environment
source .venv/bin/activate
```

### 2. Scan Trending Tokens
Scan live high-volume pairs on Solana:
```bash
python cli.py scan --limit 5 --min-liquidity 10000
```

### 3. Fetch Quote with 0.50% Fee
Retrieve Jupiter swap route and fee breakdown:
```bash
python cli.py quote --token EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v --amount 0.1
```

### 4. Swap (Dry-Run / Simulation)
Test quote execution without spending gas:
```bash
python cli.py swap --token EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v --amount 0.05
```

### 5. Run Verification Tests
```bash
pytest tests/ -v
ruff check .
```

### 6. Telegram Bot
Run the bot daemon (get a token from [@BotFather](https://t.me/BotFather)):
```bash
export TELEGRAM_BOT_TOKEN="<your-token>"
python cli.py bot
# or: python cli.py bot --token <your-token>
```
Commands: `/start`, `/help`, `/scan`, `/quote <mint> [amount_sol]`, plus inline
buttons on `/scan` results for one-tap quoting. The bot only fetches quotes —
it never constructs, signs, or sends a swap transaction.
