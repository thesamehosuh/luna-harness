"""Identity registry: deterministic peer attribution, overrides, collision safety, audit."""

from __future__ import annotations

import json

import pytest

from luna_core import db
from luna_core.identity import (
    IdentityRegistry,
    collision_digest,
    heal_identity_platform_keys,
    normalize_platform,
    sanitize_peer_id,
)

OWNER = "1000000001"
BABI = "1000000002"
DIA = "1000000004"


class FakePlatformEnum:
    """Mimics ``gateway.config.Platform.TELEGRAM``: ``str()`` is ``Platform.TELEGRAM``."""

    value = "telegram"

    def __str__(self) -> str:
        return "Platform.TELEGRAM"


@pytest.fixture()
def reg(tmp_path):
    conn = db.connect(tmp_path / "luna-state.db")
    db.init_db(conn)
    yield IdentityRegistry(conn)
    conn.close()


def test_sanitize_peer_id_is_stable_and_safe():
    assert sanitize_peer_id(OWNER) == "telegram_1000000001"
    assert sanitize_peer_id("Some.Name-42", prefix="tg_") == "tg_some_name_42"
    assert sanitize_peer_id("") == "telegram_unknown"


def test_normalize_platform_canonicalizes_every_input_shape():
    assert normalize_platform("telegram") == "telegram"
    assert normalize_platform("Telegram") == "telegram"
    assert normalize_platform(FakePlatformEnum()) == "telegram"
    # str() of an enum that slipped through as text is healed.
    assert normalize_platform("Platform.TELEGRAM") == "telegram"
    assert normalize_platform(None) == ""


def test_enum_platform_key_does_not_fork_the_registry(reg):
    """``str(Platform.TELEGRAM)`` rows and ``telegram`` rows must be the same member."""
    reg.upsert_auto(FakePlatformEnum(), OWNER, display_name="Sam")
    assert reg.get("telegram", OWNER) is not None
    assert reg.get(FakePlatformEnum(), OWNER) is not None
    again = reg.upsert_auto("telegram", OWNER, display_name="Sam Renamed")
    assert again.peer_id == "telegram_1000000001"
    assert reg.get("Platform.TELEGRAM", OWNER) is not None  # enum-str form healed too
    rows = reg.conn.execute(
        "SELECT COUNT(*) AS n FROM identity WHERE user_id = ?", (OWNER,)
    ).fetchone()
    assert rows["n"] == 1


def test_heal_identity_platform_keys_merges_forked_rows(reg):
    """Rows already written under ``Platform.TELEGRAM`` are merged into ``telegram`` on init."""
    reg.conn.execute(
        "INSERT INTO identity(platform, user_id, peer_id, display_name, is_manual) "
        "VALUES ('Platform.TELEGRAM', ?, 'telegram_1000000001', 'stale', 0)",
        (OWNER,),
    )
    reg.conn.execute(
        "INSERT INTO identity(platform, user_id, peer_id, display_name, is_manual) "
        "VALUES ('Platform.TELEGRAM', ?, 'telegram_1000000002', 'Babi', 0)",
        (BABI,),
    )
    reg.conn.commit()
    moved = heal_identity_platform_keys(reg.conn)
    assert moved == 2
    assert reg.get("telegram", BABI).display_name == "Babi"
    assert reg.conn.execute(
        "SELECT COUNT(*) AS n FROM identity WHERE platform LIKE 'Platform.%'"
    ).fetchone()["n"] == 0


def test_heal_identity_platform_keys_manual_wins_the_merge(reg):
    reg.set_manual("telegram", OWNER, peer_id="sam", display_name="Sam")
    reg.conn.execute(
        "INSERT INTO identity(platform, user_id, peer_id, display_name, role, is_manual) "
        "VALUES ('Platform.TELEGRAM', ?, 'telegram_1000000001', 'forked', 'owner', 0)",
        (OWNER,),
    )
    reg.conn.commit()
    heal_identity_platform_keys(reg.conn)
    ident = reg.get("telegram", OWNER)
    assert ident.peer_id == "sam" and ident.is_manual is True
    # The loser still backfills fields the winner is missing.
    assert ident.role == "owner"


def test_merge_unifies_two_runtime_ids_under_one_peer(reg):
    reg.upsert_auto("telegram", OWNER, display_name="Sam")
    reg.set_manual("telegram", "1000000099", display_name="Sam's alt", role="owner")
    merged = reg.merge("telegram", OWNER, "1000000099")
    assert merged is not None
    assert merged.peer_id == "telegram_1000000001"
    assert merged.user_id_alt == "1000000099"
    assert merged.role == "owner"  # backfilled from the absorbed row
    assert reg.get("telegram", "1000000099") is None  # absorbed, not duplicated
    # Both runtime ids resolve to the one peer, and the alias map covers both.
    assert reg.resolve_any("telegram", "1000000099") == "telegram_1000000001"
    aliases = reg.alias_map("telegram")
    assert aliases[OWNER] == aliases["1000000099"] == "telegram_1000000001"


def test_merge_keeps_manual_peer_id(reg):
    reg.set_manual("telegram", OWNER, peer_id="sam", display_name="Sam")
    reg.upsert_auto("telegram", "1000000099")
    merged = reg.merge("telegram", OWNER, "1000000099")
    assert merged.peer_id == "sam" and merged.is_manual is True


def test_merge_refuses_a_third_id(reg):
    reg.upsert_auto("telegram", OWNER)
    reg.merge("telegram", OWNER, "1000000099")
    with pytest.raises(ValueError):
        reg.merge("telegram", OWNER, "1000000098")


def test_merge_without_rows_is_a_noop(reg):
    assert reg.merge("telegram", "1", "2") is None
    assert reg.merge("telegram", OWNER, OWNER) is None


def test_collision_digest_is_deterministic():
    assert collision_digest("a") == collision_digest("a")
    assert collision_digest("a") != collision_digest("b")


def test_auto_upsert_learns_without_overwriting_peer_id(reg):
    first = reg.upsert_auto("telegram", BABI, display_name="Babi")
    assert first.peer_id == "telegram_1000000002"
    assert first.is_manual is False

    again = reg.upsert_auto("telegram", BABI, display_name="Babi Renamed")
    assert again.peer_id == first.peer_id  # stable
    assert again.display_name == "Babi Renamed"


def test_manual_override_wins_and_survives_auto_upsert(reg):
    reg.upsert_auto("telegram", OWNER, display_name="whatever")
    reg.set_manual("telegram", OWNER, peer_id="sam", display_name="Sam", pronouns="he/him",
                   role="owner", aliases=["sam"])

    # Auto-learn must not clobber the manual row.
    reg.upsert_auto("telegram", OWNER, display_name="clobber attempt")
    ident = reg.get("telegram", OWNER)
    assert ident.peer_id == "sam"
    assert ident.display_name == "Sam"
    assert ident.pronouns == "he/him"
    assert ident.aliases == ["sam"]
    assert ident.is_manual is True


def test_alias_map_covers_every_member(reg):
    reg.set_manual("telegram", OWNER, peer_id="sam")
    reg.upsert_auto("telegram", BABI, display_name="Babi")
    reg.upsert_auto("telegram", DIA, display_name="Dia")

    aliases = reg.alias_map("telegram")
    assert aliases[OWNER] == "sam"
    assert aliases[BABI] == "telegram_1000000002"
    assert aliases[DIA] == "telegram_1000000004"
    # No member is left unnamed.
    assert len(aliases) == 3


def test_collision_gets_digest_suffix(reg, monkeypatch):
    # Force two different ids to sanitize identically.
    import luna_core.identity as identity_mod

    monkeypatch.setattr(identity_mod, "sanitize_peer_id", lambda uid, prefix="telegram_": "telegram_same")

    a = reg.upsert_auto("telegram", "111", display_name="A")
    b = reg.upsert_auto("telegram", "222", display_name="B")
    assert a.peer_id == "telegram_same"
    assert b.peer_id == f"telegram_same_{collision_digest('222')}"
    assert a.peer_id != b.peer_id


def test_load_overrides_from_json(reg, tmp_path):
    path = tmp_path / "identity_overrides.json"
    path.write_text(
        json.dumps(
            {
                "platform": "telegram",
                "members": [
                    {"user_id": OWNER, "peer_id": "sam", "display_name": "Sam",
                     "pronouns": "he/him", "role": "owner"},
                    {"user_id": BABI, "peer_id": "babi", "display_name": "Babi"},
                ],
            }
        ),
        encoding="utf-8",
    )
    assert reg.load_overrides(path) == 2
    assert reg.resolve("telegram", OWNER) == "sam"
    assert reg.resolve("telegram", BABI) == "babi"


def test_audit_flags_unmapped_and_colliding(reg):
    # A message from an unregistered member.
    reg.conn.execute(
        "INSERT INTO messages(message_id, chat_id, user_id, user_name, is_bot, observed) "
        "VALUES ('m1', '-100', ?, 'Ghost', 0, 1)",
        ("999",),
    )
    reg.conn.commit()
    report = reg.audit()
    assert report["ok"] is False
    assert report["unmapped"][0]["user_id"] == "999"

    # Register them -> clean.
    reg.upsert_auto("telegram", "999", display_name="Ghost")
    assert reg.audit()["ok"] is True


def test_audit_flags_colliding_peers(reg):
    reg.set_manual("telegram", "111", peer_id="dup")
    reg.set_manual("telegram", "222", peer_id="dup")
    report = reg.audit()
    assert report["ok"] is False
    assert report["colliding"][0]["peer_id"] == "dup"
    assert report["colliding"][0]["n"] == 2


def test_apply_overrides_is_loaded_and_wins(reg, tmp_path, monkeypatch):
    """Manual identity files are actually applied at runtime (they used to be dead code)."""
    from luna_core.identity import apply_overrides

    path = tmp_path / "identity_overrides.json"
    path.write_text(
        json.dumps({"platform": "telegram",
                    "members": [{"user_id": OWNER, "peer_id": "sam", "display_name": "Sam",
                                 "role": "owner"}]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("LUNA_IDENTITY_OVERRIDES", str(path))
    assert apply_overrides(reg) == 1
    assert reg.resolve("telegram", OWNER) == "sam"

    # Auto-learn must not clobber the manual row once the overrides are in.
    reg.upsert_auto("telegram", OWNER, display_name="clobber attempt")
    assert reg.get("telegram", OWNER).display_name == "Sam"


def test_apply_overrides_missing_file_is_silent(reg, monkeypatch, tmp_path):
    from luna_core.identity import apply_overrides

    monkeypatch.setenv("LUNA_IDENTITY_OVERRIDES", str(tmp_path / "nope.json"))
    assert apply_overrides(reg) == 0


def test_alias_map_includes_alt_account_ids(reg):
    reg.set_manual("telegram", OWNER, peer_id="sam", user_id_alt="1000000099")
    aliases = reg.alias_map("telegram")
    assert aliases[OWNER] == "sam"
    assert aliases["1000000099"] == "sam"


def test_resolve_any_unifies_alt_accounts(reg):
    reg.set_manual("telegram", OWNER, peer_id="sam", user_id_alt="1000000099")
    assert reg.resolve_any("telegram", "1000000099") == "sam"
    assert reg.resolve_any("telegram", OWNER) == "sam"
    assert reg.resolve_any("telegram", "42") is None
