#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
cd "$DIR"

if [ -f .env ]; then
    echo "📄 Loading environment variables from .env..."
    export $(grep -v '^#' .env | xargs)
fi

if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    echo "❌ Error: TELEGRAM_BOT_TOKEN is not set."
    echo "👉 Get a token from @BotFather on Telegram, then add it to .env or export TELEGRAM_BOT_TOKEN."
    exit 1
fi

if [ -z "$PLATFORM_FEE_WALLET" ] && [ -z "$SOL_FEE_RECIPIENT" ]; then
    echo "⚠️ Warning: PLATFORM_FEE_WALLET is not set. Default fallback fee wallet will be used."
fi

source .venv/bin/activate
echo "🚀 Starting sol-dex-streamer Telegram Bot Daemon..."
exec python bot.py
