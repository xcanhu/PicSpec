"""Audit the judge without human labels.

Each probe changes an image in a known way, so the right answer to a rule's question is known
too: mirror the image and "does the person face left?" must flip; draw text on it and "is there
text?" must become yes. The share of probes a judge gets right is a measure of how far its
verdicts on that kind of rule can be trusted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

from .judge import check_image
from .llm import ChatModel
from .measure import add_grain  # noqa: F401  (re-exported for callers of audit.add_grain)
from .spec import Spec


def add_text(image: Image.Image, text: str = "SAMPLE 2026") -> Image.Image:
    out = image.convert("RGB")
    draw = ImageDraw.Draw(out)
    font = ImageFont.load_default(size=max(out.width // 9, 12))
    box = draw.textbbox((0, 0), text, font=font)
    x, y = (out.width - (box[2] - box[0])) // 2, int(out.height * 0.82)
    draw.text((x, y), text, font=font, fill="white", stroke_width=max(out.width // 250, 1), stroke_fill="black")
    return out


def blur(image: Image.Image, radius: float) -> Image.Image:
    return image.convert("RGB").filter(ImageFilter.GaussianBlur(radius * max(image.size) / 1024))


def smooth(image: Image.Image, size: float) -> Image.Image:
    """Flatten fine texture while keeping edges, the way heavy skin retouching does."""
    out = image.convert("RGB")
    for _ in range(int(size)):
        out = out.filter(ImageFilter.MedianFilter(5))
    return out


@dataclass(frozen=True)
class Probe:
    name: str
    levels: tuple[float, ...]
    apply: Callable[[Image.Image, float], Image.Image]
    expect: str  # the answer the strongest level must produce: "yes", "no" or "invert"
    about: str


PROBES: dict[str, Probe] = {p.name: p for p in (
    Probe("flip", (1,), lambda im, _: ImageOps.mirror(im.convert("RGB")), "invert",
          "mirror the image: a left/right answer must flip, every other answer must stay"),
    Probe("text", (1,), lambda im, _: add_text(im), "yes", "draw a line of text on the image"),
    Probe("grain", (4, 10, 25), add_grain, "yes", "add noise of increasing strength"),
    Probe("blur", (1.5, 4, 10), blur, "no", "blur the image more and more"),
    Probe("smooth", (2, 6), smooth, "yes", "flatten fine texture"),
)}


@dataclass
class Trial:
    image: str
    probe: str
    level: float
    rule: str
    before: bool | None
    after: bool | None
    expected: bool | None  # None when the probe says nothing for this image (e.g. flip of a "no")
    seen: str = ""

    @property
    def correct(self) -> bool | None:
        return None if self.expected is None else self.after == self.expected


@dataclass
class Audit:
    trials: list[Trial] = field(default_factory=list)
    stable: list[tuple[str, str, bool]] = field(default_factory=list)  # (source, rule, answer unchanged)

    def summary(self) -> list[dict[str, Any]]:
        """One row per probe and rule: how often the strongest level gave the known answer."""
        rows = []
        for key in dict.fromkeys((t.probe, t.rule) for t in self.trials):
            mine = [t for t in self.trials if (t.probe, t.rule) == key]
            top = max(t.level for t in mine)
            judged = [t for t in mine if t.level == top and t.correct is not None]
            row: dict[str, Any] = {"probe": key[0], "rule": key[1], "trials": len(judged),
                                   "correct": sum(bool(t.correct) for t in judged)}
            if len({t.level for t in mine}) > 1:
                row["yes_by_level"] = {
                    lvl: f"{sum(t.after is True for t in mine if t.level == lvl)}/"
                         f"{sum(1 for t in mine if t.level == lvl)}"
                    for lvl in sorted({t.level for t in mine})}
            rows.append(row)
        return rows

    def stability(self) -> dict[str, tuple[int, int]]:
        """Per source ("repeat" or "flip"): (answers that stayed the same, answers compared)."""
        out: dict[str, tuple[int, int]] = {}
        for source in dict.fromkeys(s for s, _, _ in self.stable):
            hits = [same for s, _, same in self.stable if s == source]
            out[source] = (sum(hits), len(hits))
        return out

    def to_json(self) -> dict[str, Any]:
        return {"summary": self.summary(),
                "stability": {k: {"same": a, "compared": b} for k, (a, b) in self.stability().items()},
                "trials": [{**t.__dict__, "correct": t.correct} for t in self.trials]}


def parse_probe(text: str, spec: Spec) -> tuple[Probe, str, str]:
    """Read ``probe=rule`` or ``probe=rule:yes|no`` into (probe, rule id, expected answer)."""
    name, _, rest = text.partition("=")
    rule_id, _, expect = rest.partition(":")
    if name not in PROBES or not rule_id:
        raise ValueError(f'"{text}" should look like PROBE=RULE, with PROBE one of {", ".join(PROBES)}')
    spec.rule(rule_id)  # KeyError for an unknown rule
    probe = PROBES[name]
    expect = expect or probe.expect
    if expect not in ("yes", "no", "invert") or (expect == "invert") != (probe.expect == "invert"):
        raise ValueError(f'"{text}": the expected answer for {name} must be '
                         f'{"left out" if probe.expect == "invert" else "yes or no"}')
    return probe, rule_id, expect


def audit_judge(images: dict[str, Image.Image], spec: Spec, judge: ChatModel,
                probes: list[tuple[Probe, str, str]], *, repeat: bool = True, one_by_one: bool = False,
                on_step: Callable[[str], None] | None = None,
                keep: Callable[[str, Image.Image], None] | None = None) -> Audit:
    """Run every probe on every image. ``keep`` receives each changed image, to save it."""
    audit = Audit()

    def answers(image: Image.Image, label: str) -> dict[str, tuple[bool | None, str]]:
        if on_step:
            on_step(label)
        report = check_image(image, spec, judge, one_by_one=one_by_one)
        return {v.rule_id: (v.answer, v.seen) for v in report.verdicts}

    for name, image in images.items():
        base = answers(image, f"{name}: original")
        if repeat:
            again = answers(image, f"{name}: original again")
            audit.stable += [("repeat", rid, again[rid][0] == base[rid][0]) for rid in base]
        cache: dict[tuple[str, float], dict[str, tuple[bool | None, str]]] = {}
        for probe, rule_id, expect in probes:
            for level in probe.levels:
                if (probe.name, level) not in cache:
                    changed = probe.apply(image, level)
                    if keep:
                        keep(f"{name}.{probe.name}-{level:g}", changed)
                    cache[probe.name, level] = answers(changed, f"{name}: {probe.name} {level:g}")
                    if probe.name == "flip":
                        targets = {r for p, r, _ in probes if p.name == "flip"}
                        audit.stable += [("flip", rid, cache[probe.name, level][rid][0] == base[rid][0])
                                         for rid in base if rid not in targets]
                after, seen = cache[probe.name, level][rule_id]
                before = base[rule_id][0]
                if expect == "invert":
                    expected = False if before is True else None  # only a clear "yes" must flip
                else:
                    expected = expect == "yes"
                audit.trials.append(Trial(name, probe.name, level, rule_id, before, after, expected, seen))
    return audit
