"""Turn a sentence of feedback into a proposed change to the spec.

"The skin looks too smooth" becomes a new rule, a stricter version of an existing one, or the
removal of a rule that caused the problem. Nothing is written until the caller applies it.
"""

from __future__ import annotations

import copy
import difflib
import json
from dataclasses import dataclass, field
from typing import Any

from PIL import Image

from . import library
from .llm import ChatModel, extract_json
from .spec import KINDS, LEVELS, Category, Rule, Spec, dumps

_SYSTEM = """\
You maintain a PICSPEC.md file: a list of checkable rules that every generated image must follow. \
The user gives feedback on an image or on their images in general. Turn it into the smallest change \
to the rules that would have prevented the complaint, so it does not have to be said again.

Choose, in this order of preference:
1. "modify" an existing rule when the feedback is about something a rule already covers \
(make its text more specific or stricter, fix its check question, change its level).
2. "add" a rule from the library when one fits: give its id in "library" and nothing else.
3. "add" a new rule you write yourself.
4. "remove" a rule only when the feedback says the rule itself is unwanted.

A rule has: "text" (what the image must look like, one concrete visible property, or for kind \
"forbid" the unwanted thing itself), "check" (a yes/no question that someone looking only at the image \
can answer), "expect" ("yes" or "no": the answer that means the rule is met; "no" for forbid rules whose \
question asks whether the unwanted thing is present), "kind" (texture = image look, light, colour; \
composition = subject, pose, framing; forbid = things to avoid), "level" (must or should) and optionally \
"when" (the rule only applies when this is true of the image, e.g. "a person is in the image").

Rules are persistent preferences, not descriptions of one picture: never put the subject of a single \
prompt into a rule. Feedback that is only about one image's content ("make her smile in this one") \
needs no rule: return an empty list and say so in "note". Write rule text in the language of the spec.

Reply with JSON only:
{"changes": [{"action": "add" | "modify" | "remove", "id": "<rule id; required for modify and remove, \
optional short lowercase id for add>", "library": "<library id or null>", "rule": {"text": "...", \
"check": "...", "expect": "yes" | "no", "kind": "...", "level": "...", "when": "..."}, \
"why": "<one sentence>"}], "note": "<one sentence, or empty>"}
For "modify", put only the fields that change in "rule"."""


@dataclass
class Change:
    action: str
    id: str = ""
    library: str = ""
    rule: dict[str, Any] = field(default_factory=dict)
    why: str = ""


@dataclass
class Proposal:
    changes: list[Change] = field(default_factory=list)
    note: str = ""
    skipped: list[str] = field(default_factory=list)  # why some of the model's changes were not usable


def _catalogue(lang: str) -> str:
    i = 1 if lang == "zh" else 0
    return "\n".join(f"- {e.id} [{e.kind}]: {e.text[i]}" for e in library.ENTRIES)


def propose(spec: Spec, feedback: str, model: ChatModel, images: list[Image.Image] | None = None) -> Proposal:
    """Ask ``model`` what to change in ``spec`` so that ``feedback`` need not be given again."""
    user = (f"Spec language: {'Chinese' if spec.lang == 'zh' else 'English'}\n\n"
            f"Current PICSPEC.md:\n```\n{dumps(spec)}```\n\n"
            f"Library rules that can be added by id:\n{_catalogue(spec.lang)}\n\n"
            f"Feedback: {feedback.strip()}"
            + ("\n\nThe image the feedback is about is attached." if images else ""))
    data = extract_json(model.chat(_SYSTEM, user, images=images or None))
    proposal = Proposal(note=str(data.get("note") or "") if isinstance(data, dict) else "")
    raw = data.get("changes") if isinstance(data, dict) else None
    known = {r.id for r in spec.rules}
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action", "")).casefold()
        change = Change(action, str(item.get("id") or ""), str(item.get("library") or ""),
                        item.get("rule") if isinstance(item.get("rule"), dict) else {}, str(item.get("why") or ""))
        if action in ("modify", "remove") and change.id not in known:
            proposal.skipped.append(f"{action} of unknown rule {change.id!r}")
        elif action == "add" and change.library and change.library not in {e.id for e in library.ENTRIES}:
            proposal.skipped.append(f"unknown library rule {change.library!r}")
        elif action == "add" and (change.library or change.id) in known:
            proposal.skipped.append(f"rule {(change.library or change.id)!r} is already in the spec")
        elif action == "add" and not change.library and not str(change.rule.get("text", "")).strip():
            proposal.skipped.append("a new rule without text")
        elif action in ("add", "modify", "remove"):
            proposal.changes.append(change)
        else:
            proposal.skipped.append(f"unknown action {action!r}")
    return proposal


def _set(rule: Rule, values: dict[str, Any]) -> None:
    for key in ("text", "check", "when", "prompt", "negative"):
        if isinstance(values.get(key), str):
            setattr(rule, key, " ".join(values[key].split()))
    if "expect" in values:
        v = values["expect"]
        rule.expect = v if isinstance(v, bool) else str(v).strip().casefold() in ("yes", "true", "是")
    if str(values.get("level", "")).casefold() in LEVELS:
        rule.level = str(values["level"]).casefold()


def _unique(base: str, taken: set[str]) -> str:
    if base and base not in taken:
        return base
    n = 1
    while f"{base or 'r'}{n}" in taken:
        n += 1
    return f"{base or 'r'}{n}"


def apply(spec: Spec, changes: list[Change]) -> Spec:
    """A copy of ``spec`` with ``changes`` made. The original is left alone."""
    out = copy.deepcopy(spec)
    i = 1 if out.lang == "zh" else 0
    for change in changes:
        taken = {r.id for r in out.rules}
        if change.action == "remove":
            for cat in out.categories:
                cat.rules = [r for r in cat.rules if r.id != change.id]
        elif change.action == "modify":
            _set(out.rule(change.id), change.rule)
        elif change.action == "add":
            if change.library:
                rule = library.get(change.library).rule(out.lang)
            else:
                kind = str(change.rule.get("kind", "")).casefold()
                safe = "".join(c for c in change.id.casefold() if c.isalnum() or c in "-_")[:24]
                rule = Rule(id=_unique(safe, taken), text="", kind=kind if kind in KINDS else "other")
                if rule.kind == "forbid":
                    rule.expect = False
                _set(rule, change.rule)
            home = next((c for c in out.categories if c.kind == rule.kind), None)
            if home is None:
                title = library.SECTIONS.get(rule.kind, ("Other rules", "其他"))[i]
                home = Category(title=title, kind=rule.kind)
                out.categories.append(home)
            home.rules.append(rule)
    out.categories = [c for c in out.categories if c.rules or c.notes]
    return out


def diff(before: Spec, after: Spec) -> str:
    """A unified diff between two specs in their canonical layout. Empty when nothing changed."""
    a, b = dumps(before).splitlines(), dumps(after).splitlines()
    return "\n".join(difflib.unified_diff(a, b, "PICSPEC.md", "PICSPEC.md (proposed)", lineterm="", n=1))


def to_json(proposal: Proposal) -> str:
    return json.dumps({"changes": [vars(c) for c in proposal.changes], "note": proposal.note,
                       "skipped": proposal.skipped}, ensure_ascii=False, indent=1)
