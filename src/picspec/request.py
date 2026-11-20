"""Turn a spec plus one prompt into a backend-neutral request.

The request is the common ground between image models: the user's prompt, a
list of directives (one per rule), reference images and negative terms. Each
backend decides how to say that to its own model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .spec import Rule, Spec, parse_size

_ORDER = {"texture": 0, "composition": 1, "other": 2, "forbid": 3}


@dataclass
class Directive:
    rule_id: str
    text: str
    kind: str
    level: str = "must"
    when: str = ""


@dataclass
class Reference:
    path: Path
    note: str
    rule_id: str
    level: str = "must"


@dataclass
class Request:
    prompt: str
    summary: str = ""
    directives: list[Directive] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)
    negatives: list[str] = field(default_factory=list)
    emphasize: list[str] = field(default_factory=list)
    size: tuple[int, int] | None = None
    quality: str | None = None
    seed: int = 0
    lang: str = "en"

    @property
    def rule_ids(self) -> list[str]:
        return [d.rule_id for d in self.directives]


def bare_request(prompt: str, *, size: tuple[int, int] | None = None, quality: str | None = None,
                 seed: int = 0) -> Request:
    """A request with no spec applied: what you would get by calling the model directly."""
    return Request(prompt=prompt, size=size, quality=quality, seed=seed)


def build_request(
    spec: Spec,
    prompt: str,
    *,
    only: Iterable[str] | None = None,
    skip: Iterable[str] = (),
    emphasize: Iterable[str] = (),
    size: tuple[int, int] | None = None,
    quality: str | None = None,
    seed: int = 0,
) -> Request:
    """Apply ``spec`` to ``prompt``.

    ``only`` and ``skip`` pick rules by id. ``emphasize`` names rules that failed on an
    earlier attempt: backends put them first and stress them.
    """
    known = {r.id for r in spec.rules}
    only_set = set(only) if only is not None else None
    skip_set, stress = set(skip), [i for i in emphasize]
    unknown = sorted(((only_set or set()) | skip_set | set(stress)) - known)
    if unknown:
        raise KeyError(f"no such rule: {', '.join(unknown)}")

    chosen: list[Rule] = [r for r in spec.rules
                          if (only_set is None or r.id in only_set) and r.id not in skip_set]
    chosen.sort(key=lambda r: _ORDER[r.kind])  # stable: file order within a kind

    request = Request(
        prompt=prompt.strip(),
        summary=spec.summary,
        size=size or parse_size(spec.settings.get("size")),
        quality=quality or spec.settings.get("quality"),
        seed=seed,
        lang=spec.lang,
        emphasize=[i for i in stress if i not in skip_set and (only_set is None or i in only_set)],
    )
    for r in chosen:
        request.directives.append(Directive(r.id, r.prompt or r.text, r.kind, r.level, r.when))
        if r.negative:
            request.negatives.append(r.negative)
        for ref in r.refs:
            request.references.append(Reference(spec.ref_path(ref), ref.note or r.text, r.id, r.level))
    return request
