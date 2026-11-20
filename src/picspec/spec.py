"""The PICSPEC.md format: parse it, lint it, write it back.

A spec is a Markdown file a person can read and edit by hand::

    # My portrait look

    Natural 35mm film photography.

    ## Image look
    - `t1` Fine film grain across the whole frame
      - check: Is fine film grain visible?
      - ref: refs/grain.jpg | grain strength like this

    ## Avoid
    - `f1` Over-smoothed, plastic-looking skin
      - check: Does the skin look over-smoothed or plastic?
      - expect: no

Every top-level bullet is one rule. Indented bullets are its fields. Everything
else is kept as notes, so a file survives ``loads`` followed by ``dumps``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

FORMAT_VERSION = 1
SPEC_FILENAME = "PICSPEC.md"

KINDS = ("texture", "composition", "forbid", "other")
LEVELS = ("must", "should")

# Heading words that decide what kind of rules a section holds. First match wins,
# and "avoid" words are tested first so that "不要的质感" is a forbid section.
_KIND_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("forbid", ("禁忌", "禁止", "不要", "避免", "avoid", "forbid", "never", "don't", "do not", "banned")),
    ("texture", ("质感", "画质", "质量", "光", "色", "texture", "look", "quality", "light", "tone", "color", "colour")),
    ("composition", ("构图", "主体", "姿态", "动作", "composition", "subject", "framing", "pose", "layout")),
)

# Field names, canonical first. Chinese names are accepted and written back when the spec is Chinese.
_FIELDS: dict[str, tuple[str, ...]] = {
    "check": ("check", "核对", "检查"),
    "expect": ("expect", "期望", "预期"),
    "level": ("level", "级别", "等级"),
    "when": ("when", "适用", "条件"),
    "prompt": ("prompt", "提示词"),
    "negative": ("negative", "反向", "反向提示词"),
    "ref": ("ref", "参考图", "参考"),
    "kind": ("kind", "类型"),
    "measure": ("measure", "测量"),
}
# Checks done by a tool instead of the vision judge: name -> default threshold.
MEASURES: dict[str, float] = {"face-match": 0.363}
_MEASURE = re.compile(r"^([a-z][a-z-]*)\s*(?:(?:>=|≥)\s*(-?\d+(?:\.\d+)?))?$")
_FIELD_LOOKUP = {alias.casefold(): name for name, aliases in _FIELDS.items() for alias in aliases}
_ZH_FIELD = {name: aliases[1] for name, aliases in _FIELDS.items()}

_YES = {"yes", "y", "true", "是", "有"}
_NO = {"no", "n", "false", "否", "没有", "无"}
_LEVEL_WORDS = {"must": "must", "必须": "must", "should": "should", "尽量": "should", "建议": "should"}
_KIND_ZH = {"texture": "质感", "composition": "构图", "forbid": "禁忌", "other": "其他"}
_KIND_VALUES = {**{k: k for k in KINDS}, **{v: k for k, v in _KIND_ZH.items()}}
_ID_PREFIX = {"texture": "t", "composition": "c", "forbid": "f", "other": "r"}

_FRONT_KNOWN = ("picspec", "name", "lang", "size", "quality", "backend", "judge")

_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_RULE_ID = re.compile(r"^`([A-Za-z0-9][A-Za-z0-9_.-]*)`\s*(.*)$")
_FIELD = re.compile(r"^([^:：]{1,24})[:：]\s*(.*)$")
_CJK = re.compile(r"[一-鿿]")


@dataclass
class Problem:
    """Something wrong with a spec file. ``level`` is ``"error"`` or ``"warning"``."""

    line: int
    level: str
    message: str

    def __str__(self) -> str:
        where = f"line {self.line}: " if self.line else ""
        return f"{self.level}: {where}{self.message}"


class SpecError(ValueError):
    """Raised when a spec has errors and the caller asked for a usable spec."""

    def __init__(self, problems: list[Problem], path: Path | None = None) -> None:
        self.problems, self.path = problems, path
        head = f"{path}: " if path else ""
        super().__init__(head + "; ".join(str(p) for p in problems if p.level == "error"))


@dataclass
class Ref:
    """A reference image attached to a rule. ``path`` is relative to the spec file."""

    path: str
    note: str = ""


@dataclass
class Rule:
    id: str
    text: str
    kind: str = "other"
    check: str = ""
    expect: bool = True
    level: str = "must"
    when: str = ""
    prompt: str = ""
    negative: str = ""
    refs: list[Ref] = field(default_factory=list)
    measure: str = ""
    line: int = 0
    kind_explicit: bool = False

    @property
    def measurement(self) -> tuple[str, float] | None:
        """(tool name, threshold) when a tool decides this rule, else ``None``."""
        m = _MEASURE.match(self.measure.strip().casefold())
        if not m or m.group(1) not in MEASURES:
            return None
        return m.group(1), float(m.group(2)) if m.group(2) else MEASURES[m.group(1)]

    def question(self, lang: str = "en") -> str:
        """The yes/no question a checker asks about an image for this rule."""
        if self.check:
            return self.check
        if lang == "zh":
            return f"这张图是否符合这条要求：{self.text}"
        return f"Does the image meet this requirement: {self.text}"

    @property
    def expected_answer(self) -> bool:
        """The answer to ``question()`` that means the rule passed."""
        return self.expect if self.check else True


@dataclass
class Category:
    title: str
    kind: str = "other"
    notes: list[str] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)


@dataclass
class Spec:
    name: str = ""
    lang: str = "en"
    preamble: list[str] = field(default_factory=list)
    settings: dict[str, str] = field(default_factory=dict)
    categories: list[Category] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)
    path: Path | None = None

    @property
    def rules(self) -> list[Rule]:
        return [r for c in self.categories for r in c.rules]

    @property
    def summary(self) -> str:
        """The free text under the title: an overall description sent with every prompt."""
        text = re.sub(r"<!--.*?(-->|\Z)", "", "\n".join(self.preamble), flags=re.DOTALL)
        return " ".join(s for s in (ln.strip() for ln in text.splitlines()) if s and not s.startswith(">"))

    @property
    def errors(self) -> list[Problem]:
        return [p for p in self.problems if p.level == "error"]

    @property
    def base_dir(self) -> Path:
        return self.path.parent if self.path else Path(".")

    def rule(self, rule_id: str) -> Rule:
        for r in self.rules:
            if r.id == rule_id:
                return r
        raise KeyError(rule_id)

    def ref_path(self, ref: Ref) -> Path:
        p = Path(ref.path)
        return p if p.is_absolute() else self.base_dir / p


def kind_of_heading(title: str) -> str:
    low = title.casefold()
    for kind, words in _KIND_WORDS:
        if any(w in low for w in words):
            return kind
    return "other"


def _split_front_matter(lines: list[str]) -> tuple[dict[str, tuple[str, int]], int]:
    """Return the ``key: value`` pairs between leading ``---`` lines, and the index of the first body line."""
    start = next((i for i, ln in enumerate(lines) if ln.strip()), None)
    if start is None or lines[start].strip() != "---":
        return {}, 0
    out: dict[str, tuple[str, int]] = {}
    for i in range(start + 1, len(lines)):
        s = lines[i].strip()
        if s == "---":
            return out, i + 1
        if not s or s.startswith("#"):
            continue
        key, sep, value = s.partition(":")
        if sep:
            out[key.strip().casefold()] = (value.strip().strip("\"'"), i + 1)
    return {}, 0  # never closed: treat the whole file as body


def loads(text: str, path: str | Path | None = None) -> Spec:
    """Parse spec text. Never raises for bad content: read ``spec.problems``."""
    spec = Spec(path=Path(path) if path else None)
    problems = spec.problems
    lines = text.lstrip("﻿").splitlines()
    front, body_start = _split_front_matter(lines)

    for key, (value, ln) in front.items():
        if key == "picspec":
            if value != str(FORMAT_VERSION):
                problems.append(Problem(ln, "error", f"this file is format version {value}; "
                                                     f"this PicSpec reads version {FORMAT_VERSION}"))
        elif key == "name":
            spec.name = value
        elif key == "lang":
            spec.lang = value.casefold()[:2]
        elif key in _FRONT_KNOWN:
            spec.settings[key] = value
        else:
            problems.append(Problem(ln, "warning", f'unknown setting "{key}" is ignored'))

    category: Category | None = None
    rule: Rule | None = None
    last_field: str | None = None  # the field a wrapped line continues, or None for the rule text
    wrapped = False  # True while the next indented line may continue the previous bullet
    in_fence = in_comment = False

    def note(line: str) -> None:
        (category.notes if category else spec.preamble).append(line)

    for idx in range(body_start, len(lines)):
        ln, raw = idx + 1, lines[idx].rstrip()
        stripped = raw.strip()

        if stripped.startswith(("```", "~~~")):
            in_fence, wrapped = not in_fence, False
            note(raw)
            continue
        if in_fence:
            note(raw)
            continue
        if in_comment or stripped.startswith("<!--"):
            in_comment, wrapped = "-->" not in stripped, False
            note(raw)
            continue
        if not stripped:
            wrapped = False
            if (category.notes if category else spec.preamble):
                note("")
            continue

        heading = _HEADING.match(raw)
        if heading:
            depth, title = len(heading.group(1)), heading.group(2)
            rule, wrapped = None, False
            if depth == 1 and category is None and not spec.categories:
                spec.name = spec.name or title
            else:
                category = Category(title=title, kind=kind_of_heading(title))
                spec.categories.append(category)
            continue

        bullet = _BULLET.match(raw)
        if bullet:
            indent, content = len(bullet.group(1).expandtabs(4)), bullet.group(2).strip()
            if indent < 2:
                if category is None:
                    category = Category(title="")
                    spec.categories.append(category)
                m = _RULE_ID.match(content)
                rule = Rule(id=m.group(1) if m else "", text=(m.group(2) if m else content).strip(),
                            kind=category.kind, line=ln)
                if not rule.text:
                    problems.append(Problem(ln, "error", "this rule has no text"))
                category.rules.append(rule)
                last_field, wrapped = None, True
                continue
            if rule is None:
                problems.append(Problem(ln, "warning", "indented bullet with no rule above it is ignored"))
                continue
            last_field = _set_field(rule, content, ln, problems)
            wrapped = last_field is not None
            continue

        if wrapped and rule is not None and raw[:1] in (" ", "\t"):
            if last_field is None:
                rule.text = f"{rule.text} {stripped}".strip()
            elif last_field in ("check", "when", "prompt", "negative"):
                setattr(rule, last_field, f"{getattr(rule, last_field)} {stripped}".strip())
            continue

        wrapped = False
        note(raw)

    for notes in [spec.preamble] + [c.notes for c in spec.categories]:
        while notes and not notes[-1].strip():
            notes.pop()

    if "lang" not in front:
        spec.lang = "zh" if _CJK.search(text) else "en"
    _assign_ids(spec)
    _lint(spec)
    problems.sort(key=lambda p: p.line)
    return spec


def _set_field(rule: Rule, content: str, ln: int, problems: list[Problem]) -> str | None:
    m = _FIELD.match(content)
    name = _FIELD_LOOKUP.get(m.group(1).strip().casefold()) if m else None
    if name is None:
        known = ", ".join(_FIELDS)
        problems.append(Problem(ln, "error", f'"{content[:40]}" is not a rule field. Fields are: {known}'))
        return None
    value = m.group(2).strip()
    low = value.casefold()
    if name == "expect":
        if low in _YES or low in _NO:
            rule.expect = low in _YES
        else:
            problems.append(Problem(ln, "error", f'expect must be yes or no, not "{value}"'))
    elif name == "level":
        if low in _LEVEL_WORDS:
            rule.level = _LEVEL_WORDS[low]
        else:
            problems.append(Problem(ln, "error", f'level must be must or should, not "{value}"'))
    elif name == "kind":
        if low in _KIND_VALUES:
            rule.kind, rule.kind_explicit = _KIND_VALUES[low], True
        else:
            problems.append(Problem(ln, "error", f'kind must be one of {", ".join(KINDS)}, not "{value}"'))
    elif name == "ref":
        path, _, ref_note = value.partition("|")
        if path.strip():
            rule.refs.append(Ref(path=path.strip(), note=ref_note.strip()))
        else:
            problems.append(Problem(ln, "error", "ref needs an image path"))
    elif name == "measure":
        rule.measure = value
        if rule.measurement is None:
            problems.append(Problem(ln, "error", f'measure must look like "face-match" or "face-match >= 0.4", '
                                                 f'not "{value}". Measures are: {", ".join(MEASURES)}'))
    else:
        setattr(rule, name, value)
    return name


def _assign_ids(spec: Spec) -> None:
    seen: dict[str, int] = {}
    for r in spec.rules:
        if not r.id:
            continue
        if r.id in seen:
            spec.problems.append(Problem(r.line, "error", f'rule id "{r.id}" is already used on line {seen[r.id]}'))
        else:
            seen[r.id] = r.line
    for r in spec.rules:
        if r.id:
            continue
        prefix, n = _ID_PREFIX[r.kind], 1
        while f"{prefix}{n}" in seen:
            n += 1
        r.id = f"{prefix}{n}"
        seen[r.id] = r.line


def _lint(spec: Spec) -> None:
    problems = spec.problems
    if not spec.rules:
        problems.append(Problem(0, "warning", "the spec has no rules"))
    for r in spec.rules:
        if not r.check:
            problems.append(Problem(r.line, "warning", f'rule {r.id} has no "check" question; '
                                                        "a generic question will be asked"))
        if r.kind == "forbid" and r.check and r.expect:
            problems.append(Problem(r.line, "warning", f"rule {r.id} forbids something but expects the answer "
                                                        'yes. If the check asks whether the unwanted thing '
                                                        'is present, add "expect: no"'))
        if r.measure and not r.refs:
            problems.append(Problem(r.line, "warning", f"rule {r.id} measures against a reference image "
                                                        'but has no "ref"; the judge will be asked instead'))
        if spec.path is not None:
            for ref in r.refs:
                if not spec.ref_path(ref).is_file():
                    problems.append(Problem(r.line, "warning", f"rule {r.id}: reference image "
                                                                f"{ref.path} was not found"))
    size = spec.settings.get("size")
    if size and parse_size(size) is None:
        problems.append(Problem(0, "error", f'size must look like 1024x1536, not "{size}"'))


def parse_size(value: str | None) -> tuple[int, int] | None:
    m = re.fullmatch(r"\s*(\d{2,5})\s*[xX×*]\s*(\d{2,5})\s*", value or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def load(path: str | Path, strict: bool = True) -> Spec:
    """Read a spec file. With ``strict`` a file with errors raises ``SpecError``."""
    p = Path(path)
    spec = loads(p.read_text(encoding="utf-8"), path=p)
    if strict and spec.errors:
        raise SpecError(spec.problems, p)
    return spec


def find(start: str | Path = ".") -> Path | None:
    """Look for PICSPEC.md in ``start`` and then in each parent folder."""
    here = Path(start).resolve()
    for folder in (here, *here.parents):
        candidate = folder / SPEC_FILENAME
        if candidate.is_file():
            return candidate
    return None


def dumps(spec: Spec) -> str:
    """Write a spec in its canonical layout, with every rule id spelled out."""
    zh = spec.lang == "zh"
    key = (lambda name: _ZH_FIELD[name]) if zh else (lambda name: name)
    sep = "：" if zh else ": "
    yes_no = ("是", "否") if zh else ("yes", "no")
    out: list[str] = ["---", f"picspec: {FORMAT_VERSION}", f"lang: {spec.lang}"]
    out += [f"{k}: {v}" for k, v in spec.settings.items()]
    out += ["---", ""]
    if spec.name:
        out += [f"# {spec.name}", ""]
    if spec.preamble:
        out += [*spec.preamble, ""]
    for cat in spec.categories:
        if cat.title:
            out += [f"## {cat.title}", ""]
        if cat.notes:
            out += [*cat.notes, ""]
        for r in cat.rules:
            out.append(f"- `{r.id}` {r.text}")
            fields: list[tuple[str, str]] = []
            if r.kind_explicit:
                fields.append(("kind", _KIND_ZH[r.kind] if zh else r.kind))
            if r.check:
                fields.append(("check", r.check))
                if not r.expect:
                    fields.append(("expect", yes_no[1]))
            if r.level != "must":
                fields.append(("level", "尽量" if zh else r.level))
            for name in ("when", "prompt", "negative", "measure"):
                if getattr(r, name):
                    fields.append((name, getattr(r, name)))
            fields += [("ref", f"{ref.path} | {ref.note}" if ref.note else ref.path) for ref in r.refs]
            out += [f"  - {key(name)}{sep}{value}" for name, value in fields]
        if cat.rules:
            out.append("")
    return "\n".join(out).rstrip("\n") + "\n"
