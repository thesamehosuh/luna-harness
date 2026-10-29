"""Component tests for the luna-room plugin: sidecar staging, fallback, group shaping.

Loads the plugin by file path (it is not an installed package) and drives it with fakes — no
gateway, no network.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_DIR = REPO_ROOT / "luna" / "plugins" / "luna-room"
sys.path.insert(0, str(REPO_ROOT / "luna" / "lib"))


def _load_plugin():
    spec = importlib.util.spec_from_file_location("luna_room_plugin", PLUGIN_DIR / "__init__.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


class FakeGateway:
    def __init__(self, *, with_sidecar=True, bot_id="424242"):
        self.notes = []
        self.adapters = {
            "telegram": SimpleNamespace(
                _source_session_key=lambda source: "agent:main:telegram:group:-1000000000000:u_alex",
                _bot=SimpleNamespace(id=bot_id),
            )
        }
        if not with_sidecar:
            # Simulate an upstream build where the private method was renamed.
            self._set_pending_turn_sidecar_notes = None
            self._consume_pending_turn_sidecar_notes = None

    def _set_pending_turn_sidecar_notes(self, session_key, notes):  # noqa: D401
        self.notes.append((session_key, notes))

    def _consume_pending_turn_sidecar_notes(self, session_key):  # noqa: D401
        staged = [n for (k, n) in self.notes if k == session_key]
        self.notes = [(k, n) for (k, n) in self.notes if k != session_key]
        return [x for group in staged for x in group]


class FakeSessionStore:
    def get_or_create_session(self, source):
        return SimpleNamespace(session_id="s1")


def _source(chat_type="group", chat_id="-1000000000000", user_id="u_alex", user_name="Alex"):
    return SimpleNamespace(platform="telegram", chat_type=chat_type, chat_id=chat_id,
                           user_id=user_id, user_name=user_name)


def _event(source=None, text="hello luna", message_id="m1"):
    return SimpleNamespace(
        source=source or _source(), text=text, message_id=message_id,
        message_type="text", channel_prompt="", raw_message=None,
    )


@pytest.fixture()
def room_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LUNA_INDEX_DB", str(tmp_path / "luna-state.db"))
    monkeypatch.setenv("LUNA_CHAT_ID", "-1000000000000")
    # Hermetic: never read the live $HERMES_HOME config.yaml (emoji policy etc.).
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from luna_core import text as text_mod

    text_mod._EMOJI_POLICY_CACHE = None
    mod = _load_plugin()
    yield mod
    # reset the module-level surface map between tests
    mod._SESSION_SURFACE.clear()
    text_mod._EMOJI_POLICY_CACHE = None


def test_group_turn_stages_sidecar_not_channel_prompt(room_env):
    event = _event()
    gateway = FakeGateway()
    room_env._on_pre_gateway_dispatch(event=event, gateway=gateway, session_store=FakeSessionStore())

    assert gateway.notes, "sidecar note was not staged"
    assert event.channel_prompt == "", "channel_prompt must stay untouched"
    assert getattr(event, "_luna_room_injected", False) is True
    block = gateway.notes[0][1][0]
    assert "Alex" in block
    assert "hello luna" in block


def test_attributed_group_text_populates_sender_and_strips_prefix(room_env):
    """Triggered group turns carry `[name|id]\\ntext`; the index must keep clean text + the sender."""
    event = _event(source=_source(user_id=None, user_name=None), text="[Dia|1000000004]\nreact to this")
    room_env._on_pre_gateway_dispatch(event=event, gateway=FakeGateway(), session_store=FakeSessionStore())
    conn = room_env._index_conn()
    row = conn.execute("SELECT user_id, user_name, content FROM messages WHERE message_id='m1'").fetchone()
    assert row["user_id"] == "1000000004"
    assert row["user_name"] == "Dia"
    assert row["content"] == "react to this"


def test_dm_turn_gets_only_basic_people_reference(room_env):
    event = _event(source=_source(chat_type="dm"))
    gateway = FakeGateway()
    room_env._on_pre_gateway_dispatch(event=event, gateway=gateway, session_store=FakeSessionStore())
    assert "PEOPLE.md" in str(gateway.notes) and "Alex" in str(gateway.notes)
    assert "Room context" not in str(gateway.notes)
    assert event.channel_prompt == ""
    assert getattr(event, "_luna_room_injected", False) is False


def test_other_admitted_group_has_its_own_context_without_copying_watched_history(room_env):
    first = _event(source=_source(chat_id="other-room", user_id="u_alex", user_name="Alex"))
    gateway = FakeGateway()
    room_env._on_pre_gateway_dispatch(event=first, gateway=gateway, session_store=FakeSessionStore())
    assert "PEOPLE.md" in str(gateway.notes) and "Alex" in str(gateway.notes)
    assert "Room context" in str(gateway.notes) and first.channel_prompt == ""
    second = _event(source=_source(chat_id="third-room", user_id="u_bob", user_name="Bob"))
    other = FakeGateway()
    room_env._on_pre_gateway_dispatch(event=second, gateway=other, session_store=FakeSessionStore())
    assert "Bob" in str(other.notes) and "Alex" not in str(other.notes)


def test_command_turn_gets_no_room_block_but_output_is_still_shaped(room_env):
    """Commands keep their own source/text — but their output lands on the group surface."""
    event = _event(text="/imagine a dragon", message_id="c1")
    gateway = FakeGateway()
    room_env._on_pre_gateway_dispatch(event=event, gateway=gateway, session_store=FakeSessionStore())
    assert gateway.notes == []  # no room block for commands
    shaped = room_env._on_transform_llm_output(
        response_text="here **you** go 🔥\nline2\nline3\nline4\nline5", session_id="s1")
    assert shaped is not None
    assert "🔥" not in shaped and "*" not in shaped
    assert len(shaped.splitlines()) <= 4
    # The command message is marked triggered like any message that reached the gateway.
    row = room_env._index_conn().execute(
        "SELECT triggered FROM messages WHERE message_id='c1'").fetchone()
    assert row is not None and row["triggered"] == 1


def test_injected_turns_never_touch_the_room_log(room_env):
    """Patch 0005 reuses the trigger's message_id on injected events — indexing one would
    overwrite the trigger message's content with the wake brief."""
    event = _event(text="[Someone in the group is talking to you.]", message_id="m1")
    event.internal = True
    event.metadata = {"hermes_plugin_injection": True}
    gateway = FakeGateway()
    room_env._on_pre_gateway_dispatch(event=event, gateway=gateway, session_store=FakeSessionStore())
    assert gateway.notes == []
    row = room_env._index_conn().execute(
        "SELECT content FROM messages WHERE message_id='m1'").fetchone()
    assert row is None or "talking to you" not in (row["content"] or "")


def test_other_chat_gets_directory_but_no_watched_room_history(room_env):
    event = _event(source=_source(chat_id="-999"))
    gateway = FakeGateway()
    room_env._on_pre_gateway_dispatch(event=event, gateway=gateway, session_store=FakeSessionStore())
    assert "PEOPLE.md" in str(gateway.notes)
    assert "Room context" in str(gateway.notes)


def test_drops_room_context_when_sidecar_missing(room_env):
    """Untrusted group chatter must never ride channel_prompt.

    channel_prompt enters the cached-agent signature (AGENTS.md §3 invariant 1) and is
    system-level, so a missing sidecar seam is a reason to lose the room block, not to promote
    attacker-controlled text into the highest-trust slot.
    """
    event = _event()
    gateway = FakeGateway(with_sidecar=False)
    room_env._on_pre_gateway_dispatch(event=event, gateway=gateway, session_store=FakeSessionStore())
    assert gateway.notes == []
    assert not str(getattr(event, "channel_prompt", "") or "").strip()
    assert getattr(event, "_luna_room_injected", None) is False


def test_sidecar_staging_appends_so_first_contact_notes_cannot_drop_the_room_block(room_env):
    """run_turn stages its own notes through the same one-shot setter AFTER us; a replacing
    setter silently dropped the room block exactly on a new member's first turn."""
    event = _event()
    gateway = FakeGateway()
    room_env._on_pre_gateway_dispatch(event=event, gateway=gateway,
                                      session_store=FakeSessionStore())
    assert gateway.notes, "room block was not staged"
    session_key = gateway.notes[0][0]
    # Simulate run_turn's first-contact note landing through the (wrapped) setter.
    gateway._set_pending_turn_sidecar_notes(session_key, ["first-contact note"])
    combined = gateway._consume_pending_turn_sidecar_notes(session_key)
    assert any("hello luna" in n for n in combined), "room block was clobbered by a later note"
    assert "first-contact note" in combined
    # One-shot: a second consume sees nothing.
    assert gateway._consume_pending_turn_sidecar_notes(session_key) == []


def test_group_shaping_clamps_output(room_env):
    event = _event()
    gateway = FakeGateway()
    room_env._on_pre_gateway_dispatch(event=event, gateway=gateway, session_store=FakeSessionStore())

    draft = "**one** 🔥\ntwo\nthree\nfour\nfive"
    shaped = room_env._on_transform_llm_output(response_text=draft, session_id="s1", platform="telegram")
    assert shaped is not None
    assert "🔥" not in shaped and "*" not in shaped
    assert len(shaped.splitlines()) <= 4


def test_recorded_dm_surface_keeps_the_full_assistant_contract(room_env):
    """A recorded DM must NOT get the group contract (AGENTS.md §1: full-capability assistant).

    This is the regression guard for the fail-closed change: defaulting every unknown surface to
    "group" would cap a DM answer at 4 lines, strip its emoji and delete non-English text.
    """
    room_env._remember_surface("dm-s1", {"surface": "dm", "chat_id": "42"})
    draft = "**keep** this 🔥\ncall me at 10000000100\nline three\nline four\nline five"
    assert room_env._on_transform_llm_output(response_text=draft, session_id="dm-s1") is None


def test_shaping_before_any_dispatch_is_left_alone(room_env):
    """No gateway dispatch has run in this process, so there is no surface information at all.

    These are CLI/TUI turns, where the operator asked for the full assistant. Treating "unknown"
    as "group" here is the regression this guards.
    """
    assert room_env._DISPATCH_SEEN is False
    draft = "**keep** this 🔥\nline two\nline three\nline four\nline five"
    assert room_env._on_transform_llm_output(response_text=draft, session_id="never-seen") is None


def test_broken_pipeline_still_redacts_and_caps(room_env, monkeypatch):
    """If the shape pipeline raises, the fallback must still enforce the group contract.

    Anything that escapes this hook is discarded by the dispatcher, which then ships the *raw*
    reply — so an escaping exception is a fail-open, not a no-op.
    """
    room_env._remember_surface("grp-1", {"surface": "group", "chat_id": "-100"})

    def boom(_text):
        raise RuntimeError("pipeline down")

    monkeypatch.setattr(room_env, "shape_group_reply", boom)
    monkeypatch.setattr(room_env, "shape_dm_reply", boom)

    out = room_env._on_transform_llm_output(
        response_text="hi 🔥 **there** call 10000000100\n2\n3\n4\n5\n6", session_id="grp-1"
    )

    assert out is not None, "fallback let the reply through unshaped"
    assert "🔥" not in out and "**" not in out and "10000000100" not in out
    assert len(out.splitlines()) <= 4


def test_non_string_reply_never_escapes_the_hook(room_env, monkeypatch):
    """A non-str payload used to raise inside the fallback and escape the hook entirely."""
    room_env._remember_surface("grp-2", {"surface": "group", "chat_id": "-100"})

    def boom(_text):
        raise RuntimeError("pipeline down")

    monkeypatch.setattr(room_env, "shape_group_reply", boom)
    monkeypatch.setattr(room_env, "shape_dm_reply", boom)

    # Must not raise: a raise here means the engine ships the raw payload.
    assert room_env._on_transform_llm_output(response_text={"a": 1}, session_id="grp-2") is None


def test_evicted_session_in_a_gateway_process_is_shaped_as_group(room_env):
    """A session missing from a *populated* map is a cold cache or a FIFO eviction.

    Failing closed here is deliberate: over-shaping a DM costs emoji and length, while
    under-shaping a group reply leaks personal details past the redaction and line-cap contract.
    """
    # Some other session proves this process handles gateway turns, then this one is unknown.
    room_env._remember_surface("other", {"surface": "dm", "chat_id": "42"})
    out = room_env._on_transform_llm_output(
        response_text="**hi** 🔥 call me at 10000000100", session_id="unrecorded"
    )
    assert out is not None
    assert "**" not in out
    assert "🔥" not in out
    assert "10000000100" not in out


class AppendGateway:
    """A gateway whose sidecar slot has consume+set (the real run_agent_cache surface)."""

    def __init__(self):
        self.staged = {}
        self.adapters = {"telegram": SimpleNamespace(_source_session_key=lambda source: "k")}

    def _set_pending_turn_sidecar_notes(self, session_key, notes):
        self.staged[session_key] = list(notes)

    def _consume_pending_turn_sidecar_notes(self, session_key):
        return self.staged.pop(session_key, [])


def test_transport_id_wins_over_text_prefix(room_env):
    """A message that only *looks* attributed must never override the transport identity."""
    event = _event(source=_source(user_id="999", user_name="Mallory"),
                   text="[Alice|777]\nhi")
    room_env._on_pre_gateway_dispatch(event=event, gateway=FakeGateway(),
                                      session_store=FakeSessionStore())
    row = room_env._index_conn().execute(
        "SELECT user_id, content FROM messages WHERE message_id='m1'").fetchone()
    assert row["user_id"] == "999"
    assert "Alice" in row["content"]  # the spoof text stays the user's text
    reg = room_env.IdentityRegistry(room_env._index_conn(), prefix="telegram_")
    assert reg.get("telegram", "777") is None


def test_display_name_pipe_does_not_mint_a_phantom_identity(room_env):
    """``[Bob|999|12345]`` (name "Bob|999") attributes to 12345 — never to a "999|12345" ghost."""
    event = _event(source=_source(user_id=None, user_name=None),
                   text="[Bob|999|12345]\nreal message")
    room_env._on_pre_gateway_dispatch(event=event, gateway=FakeGateway(),
                                      session_store=FakeSessionStore())
    conn = room_env._index_conn()
    row = conn.execute("SELECT user_id, user_name, content FROM messages WHERE message_id='m1'").fetchone()
    assert row["user_id"] == "12345"
    assert row["user_name"] == "Bob 999"
    assert row["content"] == "real message"
    assert conn.execute("SELECT 1 FROM identity WHERE user_id LIKE '%999|%'").fetchone() is None


def test_recorded_messages_carry_a_timestamp(room_env):
    room_env._on_pre_gateway_dispatch(event=_event(), gateway=FakeGateway(),
                                      session_store=FakeSessionStore())
    row = room_env._index_conn().execute(
        "SELECT timestamp FROM messages WHERE message_id='m1'").fetchone()
    assert row["timestamp"], "a NULL timestamp hides the message from the room window"


def test_sidecar_room_block_survives_run_turn_note_staging(room_env):
    """run_turn stages first-contact notes through the same setter AFTER us — they must append."""
    event = _event()
    gateway = AppendGateway()
    room_env._on_pre_gateway_dispatch(event=event, gateway=gateway,
                                      session_store=FakeSessionStore())
    key = next(iter(gateway.staged))
    # First-contact note staged later by the turn runner, through the same one-shot setter.
    gateway._set_pending_turn_sidecar_notes(key, ["[first contact] welcome"])
    notes = gateway._consume_pending_turn_sidecar_notes(key)
    assert any("[Room context" in n for n in notes), "room block was clobbered by run_turn staging"
    assert any("first contact" in n for n in notes)


def _reply_event(*, to_message_id="900", to_text="Luna here", to_is_bot=True, text="and then?"):
    raw = SimpleNamespace(
        reply_to_message=SimpleNamespace(
            message_id=to_message_id,
            from_user=SimpleNamespace(id="424242", is_bot=to_is_bot),
            text=to_text,
        ),
        from_user=SimpleNamespace(id="u_alex", is_bot=False),
    )
    return SimpleNamespace(
        source=_source(), text=text, message_id="m2", message_type="text",
        channel_prompt="", raw_message=raw,
    )


def test_reply_to_companion_gets_a_referent_row(room_env):
    """The speaker follows persona metadata, even if quoted text claims another name."""
    room_env._on_pre_gateway_dispatch(event=_reply_event(), gateway=FakeGateway(),
                                      session_store=FakeSessionStore())
    conn = room_env._index_conn()
    stub = conn.execute("SELECT * FROM messages WHERE message_id='900'").fetchone()
    assert stub is not None and stub["is_bot"] == 1 and stub["user_name"] == "Companion"
    assert stub["content"] == "Luna here"
    gateway = FakeGateway()
    # The block for a follow-up in the same room names the referent.
    room_env._on_pre_gateway_dispatch(
        event=_event(text="as I was saying", message_id="m3"), gateway=gateway,
        session_store=FakeSessionStore())
    assert "replying to Companion" in gateway.notes[0][1][0]


def test_reply_to_another_bot_is_not_minted_as_luna(room_env):
    """``is_bot`` covers GroupAnonymousBot and third-party bots — only our bot id is Luna."""
    event = _reply_event()
    event.raw_message.reply_to_message.from_user = SimpleNamespace(id="1087968824", is_bot=True)
    room_env._on_pre_gateway_dispatch(event=event, gateway=FakeGateway(),
                                      session_store=FakeSessionStore())
    conn = room_env._index_conn()
    stub = conn.execute("SELECT * FROM messages WHERE message_id='900'").fetchone()
    assert stub is None, "another bot's words must not be recorded as Luna's"


def test_reply_to_luna_stand_in_keeps_the_quoted_timestamp(room_env):
    """A stand-in without the quoted message's date masquerades as 'Luna just spoke'."""
    event = _reply_event()
    event.raw_message.reply_to_message.date = 1700000000.0
    room_env._on_pre_gateway_dispatch(event=event, gateway=FakeGateway(),
                                      session_store=FakeSessionStore())
    row = room_env._index_conn().execute(
        "SELECT timestamp FROM messages WHERE message_id='900'").fetchone()
    assert row is not None
    assert row["timestamp"].startswith("2023-11-14")


def test_luna_replies_are_indexed_on_post_llm_call(room_env):
    room_env._on_pre_gateway_dispatch(event=_event(), gateway=FakeGateway(),
                                      session_store=FakeSessionStore())
    room_env._on_post_llm_call(user_message="hello luna", assistant_response="hey there",
                               session_id="s1", turn_id="t1")
    row = room_env._index_conn().execute(
        "SELECT * FROM messages WHERE message_id='luna:s1:t1'").fetchone()
    assert row is not None and row["is_bot"] == 1 and row["peer_id"] == "luna"
    assert row["content"] == "hey there"


def test_luna_reply_indexing_works_across_hook_threads(room_env):
    """The bounded hooks run on fresh worker threads — the cached connection must accept them.

    With ``check_same_thread=True`` this raised sqlite3.ProgrammingError, swallowed by the
    plugin's bare except as 'luna reply indexing skipped' — Luna's replies silently never
    reached the room log in production.
    """
    import threading

    room_env._on_pre_gateway_dispatch(event=_event(), gateway=FakeGateway(),
                                      session_store=FakeSessionStore())
    errors = []

    def worker():
        try:
            room_env._on_post_llm_call(user_message="hello luna", assistant_response="from a worker",
                                       session_id="s1", turn_id="tw")
        except Exception as exc:  # pragma: no cover - the bug under test
            errors.append(exc)

    t = threading.Thread(target=worker)
    t.start()
    t.join(timeout=5)
    assert errors == []
    row = room_env._index_conn().execute(
        "SELECT content FROM messages WHERE message_id='luna:s1:tw'").fetchone()
    assert row is not None and row["content"] == "from a worker"


def test_post_llm_call_ignores_dm_sessions(room_env):
    room_env._on_post_llm_call(user_message="hi", assistant_response="hello",
                               session_id="dm-session", turn_id="t1")
    row = room_env._index_conn().execute(
        "SELECT * FROM messages WHERE message_id LIKE 'luna:dm-session:%'").fetchone()
    assert row is None
