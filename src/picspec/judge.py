"""Check a finished image against the rules of a spec, one yes/no question per rule."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable

from PIL import Image

from .llm import ChatModel, extract_json
from .spec import Rule, Spec

PASS, FAIL, NOT_APPLICABLE, UNKNOWN = "pass", "fail", "n/a", "unknown"

_SYSTEM = """\
You inspect an image against a list of questions. Be strict and literal: judge only what is visible, \
and do not give the image the benefit of the doubt.

For each question:
1. In "seen", say in one short sentence what you actually see that bears on the question.
2. In "answer", give "yes" or "no".
3. If the question has a "condition" and that condition is not true for this image, answer "na" instead.

Reply with JSON only, in this shape, with one entry per question and the same ids:
{"answers": [{"id": "<id>", "seen": "<one sentence>", "answer": "yes" | "no" | "na"}]}"""

_CROP_NOTE = ("Two images are attached. The first is the whole image. The second is a crop from its centre "
              "at full resolution: use it for fine detail such as grain, noise and sharpness.")

_YES = {"yes", "y", "true", "是", "有", "对"}
_NO = {"no", "n", "false", "否", "没有", "不是", "无"}
_NA = {"na", "n/a", "not applicable", "不适用", "无关"}


@dataclass
class Verdict:
    rule_id: str
    status: str
    seen: str = ""
    level: str = "must"

    @property
    def failed(self) -> bool:
        return self.status in (FAIL, UNKNOWN)


@dataclass
class Report:
    verdicts: list[Verdict] = field(default_factory=list)

    @property
    def failed(self) -> list[str]:
        """Ids of the rules that were not met, must-level rules first."""
        bad = [v for v in self.verdicts if v.failed]
        return [v.rule_id for v in sorted(bad, key=lambda v: v.level != "must")]

    @property
    def must_failed(self) -> list[str]:
        return [v.rule_id for v in self.verdicts if v.failed and v.level == "must"]

    @property
    def ok(self) -> bool:
        """True when every must-level rule that applies was met."""
        return not self.must_failed

    @property
    def counts(self) -> tuple[int, int]:
        """(rules met, rules that applied)."""
        applied = [v for v in self.verdicts if v.status != NOT_APPLICABLE]
        return sum(v.status == PASS for v in applied), len(applied)

    @property
    def rank(self) -> tuple[int, int]:
        """Lower is better: must-level failures, then all failures."""
        return len(self.must_failed), len(self.failed)

    def to_json(self) -> list[dict[str, Any]]:
        return [{"rule": v.rule_id, "status": v.status, "seen": v.seen} for v in self.verdicts]


def _views(image: Image.Image, rules: list[Rule], crop: int = 768) -> list[Image.Image]:
    """The whole image, plus a full-resolution centre crop when texture rules need fine detail."""
    views = [image]
    if any(r.kind == "texture" for r in rules) and max(image.size) > 1536:
        w, h = image.size
        side = min(crop, w, h)
        left, top = (w - side) // 2, (h - side) // 2
        views.append(image.crop((left, top, left + side, top + side)))
    return views


def _ask(image: Image.Image, rules: list[Rule], judge: ChatModel, lang: str) -> dict[str, tuple[str, str]]:
    views = _views(image, rules)
    questions = [{"id": r.id, "question": r.question(lang), **({"condition": r.when} if r.when else {})}
                 for r in rules]
    user = ("Questions:\n" + json.dumps(questions, ensure_ascii=False, indent=1)
            + ("\n\n" + _CROP_NOTE if len(views) > 1 else ""))
    try:
        data = extract_json(judge.chat(_SYSTEM, user, images=views))
    except ValueError:
        return {}
    answers = data.get("answers") if isinstance(data, dict) else None
    out: dict[str, tuple[str, str]] = {}
    for item in answers if isinstance(answers, list) else []:
        if isinstance(item, dict) and "id" in item:
            out[str(item["id"])] = (str(item.get("answer", "")).strip().casefold(), str(item.get("seen", "")))
    return out


def check_image(image: Image.Image, spec: Spec, judge: ChatModel, *, only: Iterable[str] | None = None,
                one_by_one: bool = False) -> Report:
    """Ask ``judge`` every rule's question about ``image``.

    By default all questions go in one request. ``one_by_one`` sends one request per rule,
    which costs more but stops one answer from colouring the next.
    """
    wanted = set(only) if only is not None else None
    rules = [r for r in spec.rules if wanted is None or r.id in wanted]
    if not rules:
        return Report()
    batches = [[r] for r in rules] if one_by_one else [rules]
    answers: dict[str, tuple[str, str]] = {}
    for batch in batches:
        got = _ask(image, batch, judge, spec.lang)
        missing = [r for r in batch if r.id not in got]
        if missing and not one_by_one and len(batch) > 1:
            got.update(_ask(image, missing, judge, spec.lang))  # ask again for the ones the reply skipped
        answers.update(got)

    report = Report()
    for r in rules:
        answer, seen = answers.get(r.id, ("", ""))
        if answer in _NA and r.when:
            status = NOT_APPLICABLE
        elif answer in _YES or answer in _NO:
            status = PASS if (answer in _YES) == r.expected_answer else FAIL
        else:
            status = UNKNOWN
        report.verdicts.append(Verdict(r.id, status, seen, r.level))
    return report
