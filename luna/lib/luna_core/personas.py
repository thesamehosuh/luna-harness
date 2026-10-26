"""One persona library for Setup and Character. Prompts contain character, not product help."""
from pathlib import Path

SOUL_ROOT = Path(__file__).resolve().parents[2] / "soul"
PRESETS = (
    ("generic", "Easygoing", "Warm, observant, comfortable with quiet.", "okay, serious question or wildly specific tangent?", "DEFAULT.md"),
    ("warm-friend", "Warm friend", "Attentive, quietly playful.", "wait, how did that thing you were nervous about go?", "presets/warm-friend.md"),
    ("dry-wit", "Dry wit", "Good timing. A raised eyebrow.", "a bold plan. several laws of physics have concerns.", "presets/dry-wit.md"),
    ("curious-mind", "Curious mind", "Odd connections, interesting detours.", "hang on, that reminds me of something wonderfully strange.", "presets/curious-mind.md"),
)


def library(current=""):
    presets = [dict(id=id_, name=name, description=description, sample=sample,
                    content=(SOUL_ROOT / filename).read_text(encoding="utf-8"))
               for id_, name, description, sample, filename in PRESETS]
    for preset in presets:
        preset["is_current"] = bool(current.strip()) and current.strip() == preset["content"].strip()
    # A seeded starter isn't an extra, indistinguishable "current" choice.
    if current.strip() and all(current.strip() != preset["content"].strip() for preset in presets):
        presets.insert(0, dict(id="current", name="Your current persona", description="",
                              sample="", content=current, is_current=True))
    return presets
