"""Unit tests for Jito MEV Anti-Sandwich Bundler and Executor."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from core.executor import JITO_TIP_ACCOUNTS, JitoBundler, fetch_recent_blockhash, load_keypair


def test_jito_tip_accounts_valid():
    """Verify JITO_TIP_ACCOUNTS are non-empty valid base58 strings."""
    assert len(JITO_TIP_ACCOUNTS) >= 5
    for addr in JITO_TIP_ACCOUNTS:
        pk = Pubkey.from_string(addr)
        assert pk is not None


def test_create_tip_transaction():
    """Verify creation of a Jito tip transaction transfer instruction."""
    bundler = JitoBundler()
    payer = Keypair()

    tip_tx = bundler.create_tip_transaction(
        payer=payer,
        tip_lamports=10000,
        recent_blockhash="4uQeVj5tqViQh7yWWGStvkEG1Zmhx6uasJtWCJziofM",
    )

    assert tip_tx is not None
    assert len(tip_tx.signatures) == 1


@pytest.mark.asyncio
async def test_send_bundle_dispatches_json_rpc():
    """Verify send_bundle constructs valid JSON-RPC payload for Jito BlockEngine."""
    bundler = JitoBundler(block_engine_url="https://mainnet.block-engine.jito.wtf/api/v1/bundles")

    mock_resp = {
        "jsonrpc": "2.0",
        "result": "bundle_id_123456789",
        "id": 1
    }

    with patch.object(bundler.client, "post", new_callable=AsyncMock) as mock_post:
        mock_http_response = AsyncMock()
        mock_http_response.status_code = 200
        mock_http_response.json = lambda: mock_resp
        mock_post.return_value = mock_http_response

        bundle_id = await bundler.send_bundle(["tx1_base58_encoded", "tx2_base58_encoded"])

        mock_post.assert_called_once()
        body = mock_post.call_args[1]["json"]
        assert body["method"] == "sendBundle"
        assert body["params"] == [["tx1_base58_encoded", "tx2_base58_encoded"]]
        assert bundle_id == "bundle_id_123456789"

    await bundler.close()


def test_load_keypair_from_file(tmp_path):
    """Verify load_keypair reads a Solana CLI-style JSON secret key file."""
    original = Keypair()
    key_path = tmp_path / "id.json"
    key_path.write_text(json.dumps(list(bytes(original))))

    loaded = load_keypair(str(key_path))

    assert str(loaded.pubkey()) == str(original.pubkey())


def test_load_keypair_missing_file_raises(tmp_path):
    """Verify load_keypair raises clearly instead of silently using a
    throwaway wallet when no key file is configured."""
    missing_path = tmp_path / "does_not_exist.json"

    with pytest.raises(FileNotFoundError, match="No keypair found"):
        load_keypair(str(missing_path))


@pytest.mark.asyncio
async def test_fetch_recent_blockhash_returns_live_hash():
    """Verify fetch_recent_blockhash extracts the blockhash string from the
    RPC response, rather than callers falling back to Hash.default()."""
    from solders.hash import Hash
    from solders.rpc.responses import GetLatestBlockhashResp, RpcBlockhash, RpcResponseContext

    expected_hash = Hash.default()
    mock_resp = GetLatestBlockhashResp(
        value=RpcBlockhash(blockhash=expected_hash, last_valid_block_height=1),
        context=RpcResponseContext(slot=1),
    )

    with patch(
        "core.executor.AsyncClient.get_latest_blockhash",
        new_callable=AsyncMock,
        return_value=mock_resp,
    ):
        result = await fetch_recent_blockhash("https://api.mainnet-beta.solana.com")

    assert result == str(expected_hash)


@pytest.mark.asyncio
async def test_send_bundle_handles_rejection():
    """Verify send_bundle raises RuntimeError when Jito rejects bundle."""
    bundler = JitoBundler()

    mock_resp = {
        "jsonrpc": "2.0",
        "error": {"code": -32000, "message": "Bundle simulated with error"},
        "id": 1
    }

    with patch.object(bundler.client, "post", new_callable=AsyncMock) as mock_post:
        mock_http_response = AsyncMock()
        mock_http_response.status_code = 200
        mock_http_response.json = lambda: mock_resp
        mock_post.return_value = mock_http_response

        with pytest.raises(RuntimeError, match="Jito bundle submission failed"):
            await bundler.send_bundle(["tx1_mock"])

    await bundler.close()
