"""Peer materialization: alias map + cards written into honcho.json."""

from __future__ import annotations

import json

import pytest

from luna_core import db
from luna_core.identity import IdentityRegistry
from luna_core.peers import generate_alias_map, peer_cards, update_honcho_aliases

OWNER, BABI = "1000000001", "1000000002"


@pytest.fixture()
def reg(tmp_path):
    conn = db.connect(tmp_path / "luna-state.db")
    db.init_db(conn)
    r = IdentityRegistry(conn)
    r.set_manual("telegram", OWNER, peer_id="sam", display_name="Sam", pronouns="he/him",
                 role="owner", aliases=["sam"])
    r.upsert_auto("telegram", BABI, display_name="Babi")
    yield r
    conn.close()


def test_generate_alias_map_names_everyone(reg):
    aliases = generate_alias_map(reg)
    assert aliases == {OWNER: "sam", BABI: "telegram_1000000002"}


def test_peer_cards_include_identity_facts(reg):
    cards = {c["peer_id"]: c["card"] for c in peer_cards(reg)}
    assert any("name: Sam" in f for f in cards["sam"])
    assert any("pronouns: he/him" in f for f in cards["sam"])
    assert any("role: owner" in f for f in cards["sam"])


def test_update_honcho_aliases_preserves_other_config(reg, tmp_path):
    honcho = tmp_path / "honcho.json"
    honcho.write_text(
        json.dumps({"hosts": {"hermes": {"peerName": "sam", "workspace": "luna"}},
                    "baseUrl": "http://localhost:8000"}),
        encoding="utf-8",
    )
    n = update_honcho_aliases(honcho, reg)
    assert n == 2

    data = json.loads(honcho.read_text(encoding="utf-8"))
    assert data["baseUrl"] == "http://localhost:8000"
    assert data["hosts"]["hermes"]["peerName"] == "sam"
    assert data["hosts"]["hermes"]["userPeerAliases"][OWNER] == "sam"
    assert data["hosts"]["hermes"]["userPeerAliases"][BABI] == "telegram_1000000002"


def test_update_honcho_aliases_creates_file_when_missing(reg, tmp_path):
    honcho = tmp_path / "nested" / "honcho.json"
    assert update_honcho_aliases(honcho, reg) == 2
    assert honcho.exists()


def test_update_honcho_aliases_skips_noop_writes(reg, tmp_path):
    """Upstream caches honcho.json on mtime — rewriting an identical map must not churn it."""
    honcho = tmp_path / "honcho.json"
    update_honcho_aliases(honcho, reg)
    mtime = honcho.stat().st_mtime_ns
    assert update_honcho_aliases(honcho, reg) == 2  # same map -> no write
    assert honcho.stat().st_mtime_ns == mtime
    # A new member does change the map.
    reg.upsert_auto("telegram", "1000000005", display_name="New Kid")
    assert update_honcho_aliases(honcho, reg) == 3
    assert honcho.stat().st_mtime_ns != mtime
