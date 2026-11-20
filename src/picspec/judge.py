"""Check a finished image against the rules of a spec, one yes/no question per rule."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable

from PIL import Image

from . import face as face_tools
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

_CROP_NOTE = ("Image 1 is the whole image under inspection. Image 2 is a crop from its centre at full resolution: "
              "use it for fine detail such as grain, noise and sharpness.")

_REF_NOTE = ("Reference images follow the image under inspection. Each belongs to one question: compare the inspected "
             "image with it for that question only, and never treat a reference as the image being judged.")
MAX_REFERENCES = 6

_YES = {"yes", "y", "true", "是", "有", "对"}
_NO = {"no", "n", "false", "否", "没有", "不是", "无"}
_NA = {"na", "n/a", "not applicable", "不适用", "无关"}


@dataclass
class Verdict:
    rule_id: str
    status: str
    seen: str = ""
    level: str = "must"
    answer: bool | None = None  # the judge's raw yes/no; None for n/a or an unusable reply
    by: str = "judge"  # "judge" or the name of the tool that decided

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
        return [{"rule": v.rule_id, "status": v.status, "seen": v.seen, **({"by": v.by} if v.by != "judge" else {})}
                for v in self.verdicts]


_FACE_NOTE = ("Image {n} is a close-up of the main face, cut from the inspected image at full resolution: use it for "
              "skin, eyes and expression.")
# A face shorter than this share of the image height is too small for the judge to see skin detail.
_SMALL_FACE = 0.4


def _views(image: Image.Image, rules: list[Rule], faces: Any = None, crop: int = 768) -> tuple[list[Image.Image], str]:
    """The whole image plus close-ups the judge needs for fine detail, and a note that explains them."""
    views, notes = [image], []
    if any(r.kind == "texture" for r in rules) and max(image.size) > 1536:
        w, h = image.size
        side = min(crop, w, h)
        left, top = (w - side) // 2, (h - side) // 2
        views.append(image.crop((left, top, left + side, top + side)))
        notes.append(_CROP_NOTE)
    if faces is not None:
        try:
            found = faces.detect(image)
        except Exception:  # a detector failure must not stop the check
            found = []
        if found and found[0].box[3] < _SMALL_FACE * image.height:
            views.append(face_tools.face_crop(image, found[0]))
            notes.append(_FACE_NOTE.format(n=len(views)))
    return views, "\n".join(notes)


def _measure(image: Image.Image, rule: Rule, spec: Spec, faces: Any) -> tuple[str, str, str] | None:
    """Decide ``rule`` with a tool. Returns (answer, seen, tool name), or ``None`` to leave it to the judge."""
    wanted = rule.measurement
    if wanted is None or faces is None:
        return None
    name, threshold = wanted
    try:
        found = faces.detect(image)
    except Exception:
        return None
    usable = [f for f in found if not getattr(f, "profile", False)]
    if not usable:
        why = "the face is turned too far to compare" if found else "no face was found to compare"
        return ("na" if rule.when else ("no" if rule.expect else "yes")), why, name
    best: tuple[float, str] | None = None  # several references (front, three-quarter view...): the closest counts
    for ref in rule.refs:
        try:
            score = faces.similarity(image, Image.open(spec.ref_path(ref)).convert("RGB"))
        except Exception:
            continue
        if score is not None and (best is None or score > best[0]):
            best = (score, ref.path)
    if best is None:
        return None
    return ("yes" if best[0] >= threshold else "no",
            f"face similarity {best[0]:.2f} against {best[1]}; {threshold:.2f} or more counts as the same person",
            name)


def _references(rules: list[Rule], spec: Spec) -> list[tuple[list[str], Image.Image]]:
    """Reference images the judge should compare against, one per file: (ids of the questions it serves, image)."""
    found: dict[str, tuple[list[str], Image.Image]] = {}
    for r in rules:
        for ref in r.refs:
            key = str(spec.ref_path(ref))
            if key in found:
                if r.id not in found[key][0]:
                    found[key][0].append(r.id)
                continue
            if len(found) == MAX_REFERENCES:
                continue
            try:
                found[key] = ([r.id], Image.open(key).convert("RGB"))
            except OSError:
                continue
    return list(found.values())


def _ask(image: Image.Image, rules: list[Rule], judge: ChatModel, spec: Spec,
         faces: Any = None) -> dict[str, tuple[str, str]]:
    lang = spec.lang
    views, view_note = _views(image, rules, faces)
    refs = _references(rules, spec)
    questions = [{"id": r.id, "question": r.question(lang), **({"condition": r.when} if r.when else {})}
                 for r in rules]
    user = (("Write every \"seen\" sentence in Chinese.\n\n" if lang == "zh" else "")
            + "Questions:\n" + json.dumps(questions, ensure_ascii=False, indent=1)
            + ("\n\n" + view_note if view_note else ""))
    if refs:
        lines = [f"- image {len(views) + n}: reference for question{'s' if len(ids) > 1 else ''} {', '.join(ids)}"
                 for n, (ids, _) in enumerate(refs, 1)]
        user += "\n\n" + _REF_NOTE + "\n" + "\n".join(lines)
    try:
        data = extract_json(judge.chat(_SYSTEM, user, images=views + [im for _, im in refs]))
    except ValueError:
        return {}
    answers = data.get("answers") if isinstance(data, dict) else None
    out: dict[str, tuple[str, str]] = {}
    for item in answers if isinstance(answers, list) else []:
        if isinstance(item, dict) and "id" in item:
            out[str(item["id"])] = (str(item.get("answer", "")).strip().casefold(), str(item.get("seen", "")))
    return out


def check_image(image: Image.Image, spec: Spec, judge: ChatModel, *, only: Iterable[str] | None = None,
                one_by_one: bool = False, faces: Any = "auto") -> Report:
    """Ask ``judge`` every rule's question about ``image``.

    By default all questions go in one request. ``one_by_one`` sends one request per rule,
    which costs more but stops one answer from colouring the next.

    ``faces`` is a :class:`picspec.face.FaceTools`, ``None`` to do without, or ``"auto"`` to use
    them when they are installed. With them, rules that have a ``measure`` are decided by the tool
    and the judge also gets a close-up of the main face when it is small in the frame.
    """
    if faces == "auto":
        faces = face_tools.shared()
    wanted = set(only) if only is not None else None
    rules = [r for r in spec.rules if wanted is None or r.id in wanted]
    if not rules:
        return Report()
    measured: dict[str, tuple[str, str, str]] = {}
    for r in rules:
        result = _measure(image, r, spec, faces)
        if result is not None:
            measured[r.id] = result
    asked = [r for r in rules if r.id not in measured]
    batches = [[r] for r in asked] if one_by_one else ([asked] if asked else [])
    answers: dict[str, tuple[str, str]] = {k: v[:2] for k, v in measured.items()}
    for batch in batches:
        got = _ask(image, batch, judge, spec, faces)
        missing = [r for r in batch if r.id not in got]
        if missing and not one_by_one and len(batch) > 1:
            got.update(_ask(image, missing, judge, spec, faces))  # ask again for the ones the reply skipped
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
        raw = (answer in _YES) if status in (PASS, FAIL) else None
        report.verdicts.append(Verdict(r.id, status, seen, r.level, raw, measured[r.id][2] if r.id in measured
                                       else "judge"))
    return report
