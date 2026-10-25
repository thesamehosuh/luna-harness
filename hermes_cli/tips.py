"""Random tips shown at CLI session start to help users discover features."""

import random

# Home paths are rendered at call time so profile-scoped commands use their active home.
TIPS = [
    # Slash commands
    "/bg <prompt> runs a task in a separate session; /btw <question> asks a side question without interrupting.",
    "/branch forks the current session so you can explore another direction.",
    "/compress condenses conversation context when a session gets long.",
    "/rollback lists filesystem checkpoints and can restore files the agent changed.",
    "/queue <prompt> queues a message for the next turn; /steer <prompt> redirects after the next tool call.",
    "/title <name> names a session; /resume <name> returns to a named session.",
    "/undo backs up user turns and lets you re-prompt; /retry resends your last message.",
    "/model [name] switches models for this session; /model --global changes the saved default.",
    "/reasoning <level> changes reasoning depth when the model supports it.",
    "/status shows session information; /context shows a detailed context breakdown.",
    "/agents lists active agents and background tasks; /stop stops background processes.",
    "/new starts a fresh session in place; /history shows the current conversation.",
    "/cron lets you review and manage scheduled tasks.",
    "Use /help to browse available commands. Installed skills may also appear as slash commands.",
    # Attachments and context
    "Use @file:path/to/file to attach a file, @folder:path/ for a directory, or @diff for unstaged changes.",
    "@url:https://example.com fetches a web page; combine multiple @ references in one prompt.",
    "Alt+V pastes a clipboard image into the CLI conversation.",
    "Tab accepts an auto-suggestion or completes a slash command. Ctrl+C interrupts a running turn.",
    # Luna companion and dashboard
    "Use the dashboard to shape your character and voice, tune when Luna speaks, and manage people in the room.",
    "The Behaviour page controls when Luna responds; the People page manages peer identity mappings.",
    "The dashboard Help page explains wakes, memory, privacy, security, and appearance.",
    "Use the dashboard for Luna settings; terminal commands are for development and debugging.",
    "The Character page lets you choose a persona and adjust Luna's group-chat style.",
    "Use the dashboard Cron page to manage scheduled tasks and their delivery targets.",
    "In group chats, Luna keeps replies short and avoids sharing other members' personal details.",
    "Luna defaults to silence in group chats unless there is a reason to speak.",
    "In your direct messages, Luna can use tools, files, terminal access, and scheduled tasks.",
    "Room memory helps Luna remember people and context; the dashboard Help explains what is stored.",
    "A local Honcho stack can provide memory while keeping its data on your server.",
    # Engine-compatible developer guidance
    "In a project, `.hermes.md` can provide context to the agent; `AGENTS.md` is also supported.",
    "/plan writes an implementation plan under `.hermes/plans/` without executing it.",
    "Python integrations can use the engine tools namespace: `from hermes_tools import ...`.",
    "The active home path is `{HERMES_HOME}`; the Luna CLI defaults to `~/.luna`.",
    "The Luna entrypoint accepts `LUNA_HOME`; `HERMES_HOME` remains supported for engine integrations.",
    "Use `luna doctor` to inspect installation health during development.",
    "Use `luna dashboard` to open the Luna settings and Help interface.",
]


def get_random_tip(exclude_recent: int = 0) -> str:
    """Return a random tip, expanding paths against the active runtime home."""
    tip = random.choice(TIPS)
    if "{HERMES_HOME}" not in tip:
        return tip
    from hermes_constants import get_hermes_home

    return tip.replace("{HERMES_HOME}", str(get_hermes_home()))


# Task-oriented example prompts for the empty composer. Kept generic — Luna is
# not a coding-only agent, so they must fit any project or none.
COMPOSER_PLACEHOLDERS = [
    "Ask anything, or type / for commands…",
    "Summarize what's in this folder",
    "Draft a reply to the last email in my inbox",
    "Plan a feature, then build it step by step",
    "Find and fix a failing test",
    "Research this topic and write me a brief",
    "What changed in this repo recently?",
    "Turn these notes into a to-do list",
    "Explain this error and how to fix it",
    "Set a reminder or schedule a recurring task",
    "Type / to browse commands, or Ctrl+P for the palette"]


def get_random_composer_placeholder() -> str:
    """Return a rotating task-oriented placeholder for the empty composer."""
    return random.choice(COMPOSER_PLACEHOLDERS)
