"""Generate, check every rule, then repair the best image or try again with the failed rules stressed."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from PIL import Image

from . import face as face_tools
from . import measure
from .backends.base import Backend, Result
from .judge import Report, check_image
from .llm import ChatModel
from .request import build_request
from .spec import Spec


@dataclass
class Attempt:
    round: int
    seed: int
    result: Result
    report: Report
    stressed: list[str] = field(default_factory=list)
    method: str = "generate"  # generate, edit, or fix (repaired in code, no image request)
    source: int | None = None  # index of the attempt this one was edited from

    @property
    def image(self) -> Image.Image:
        return self.result.image


@dataclass
class Outcome:
    attempts: list[Attempt]

    @property
    def best(self) -> Attempt:
        return min(self.attempts, key=lambda a: a.report.rank)  # the earliest attempt wins a tie

    @property
    def ok(self) -> bool:
        return self.best.report.ok


def generate_checked(
    spec: Spec,
    prompt: str,
    backend: Backend,
    judge: ChatModel,
    *,
    rounds: int = 3,
    candidates: int = 1,
    seed: int = 0,
    only: Iterable[str] | None = None,
    skip: Iterable[str] = (),
    one_by_one: bool = False,
    repair: str = "auto",
    local_fix: bool = True,
    faces: Any = "auto",
    on_attempt: Callable[[Attempt], None] | None = None,
    **request_options: Any,
) -> Outcome:
    """Run up to ``rounds`` rounds of ``candidates`` images each, stopping at the first round with
    an image that meets every must-level rule.

    After a failed round, ``repair`` decides what the next one does with the rules the best image failed:

    - ``"edit"``: edit the best image so that only those rules change (backends that can edit).
    - ``"regenerate"``: generate again from the prompt with those rules stressed.
    - ``"auto"``: edit, and fall back to generating again after a round of edits that made nothing better.

    Before any of that, with ``local_fix`` on, failures that code can repair are repaired on the spot at
    no image cost: a face too small for the framing rule is cropped in, missing grain is added. The
    repaired image is checked again and joins the attempts with method ``"fix"``.
    """
    if repair not in ("auto", "edit", "regenerate"):
        raise ValueError(f"repair must be auto, edit or regenerate, not {repair!r}")
    only_ids = list(only) if only is not None else None
    skip_ids = list(skip)
    attempts: list[Attempt] = []
    stressed: list[str] = []
    editing = False
    if faces == "auto":
        faces = face_tools.shared()

    def record(attempt: Attempt) -> None:
        attempts.append(attempt)
        if on_attempt:
            on_attempt(attempt)

    for round_no in range(1, max(rounds, 1) + 1):
        base = attempts.index(Outcome(attempts).best) if attempts else None
        for _ in range(max(candidates, 1)):
            request = build_request(spec, prompt, only=only_ids, skip=skip_ids, emphasize=stressed,
                                    seed=seed + len(attempts), **request_options)
            if editing and base is not None:
                result = backend.repair(attempts[base].image, request)
            else:
                result = backend.generate(request)
            report = check_image(result.image, spec, judge, only=request.rule_ids, one_by_one=one_by_one,
                                 faces=faces)
            record(Attempt(round_no, request.seed, result, report, list(stressed),
                           "edit" if editing else "generate", base if editing else None))
            if local_fix and report.failed:
                fixed, worked_on = measure.fix(result.image, spec, report.failed, faces)
                if worked_on:
                    again = check_image(fixed, spec, judge, only=request.rule_ids, one_by_one=one_by_one,
                                        faces=faces)
                    record(Attempt(round_no, request.seed, Result(fixed, result.rendered, {"fixed": worked_on}),
                                   again, worked_on, "fix", len(attempts) - 1))
        outcome = Outcome(attempts)
        if outcome.ok:
            break
        improved = base is None or attempts.index(outcome.best) != base
        stressed = outcome.best.report.failed
        editing = backend.caps.edit and (repair == "edit" or (repair == "auto" and (improved or not editing)))
    return Outcome(attempts)
