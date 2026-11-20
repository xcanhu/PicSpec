"""Generate, check every rule, then repair the best image or try again with the failed rules stressed."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from PIL import Image

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
    method: str = "generate"
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
    on_attempt: Callable[[Attempt], None] | None = None,
    **request_options: Any,
) -> Outcome:
    """Run up to ``rounds`` rounds of ``candidates`` images each, stopping at the first round with
    an image that meets every must-level rule.

    After a failed round, ``repair`` decides what the next one does with the rules the best image failed:

    - ``"edit"``: edit the best image so that only those rules change (backends that can edit).
    - ``"regenerate"``: generate again from the prompt with those rules stressed.
    - ``"auto"``: edit, and fall back to generating again after a round of edits that made nothing better.
    """
    if repair not in ("auto", "edit", "regenerate"):
        raise ValueError(f"repair must be auto, edit or regenerate, not {repair!r}")
    only_ids = list(only) if only is not None else None
    skip_ids = list(skip)
    attempts: list[Attempt] = []
    stressed: list[str] = []
    editing = False
    for round_no in range(1, max(rounds, 1) + 1):
        base = attempts.index(Outcome(attempts).best) if attempts else None
        for _ in range(max(candidates, 1)):
            request = build_request(spec, prompt, only=only_ids, skip=skip_ids, emphasize=stressed,
                                    seed=seed + len(attempts), **request_options)
            if editing and base is not None:
                result = backend.repair(attempts[base].image, request)
            else:
                result = backend.generate(request)
            report = check_image(result.image, spec, judge, only=request.rule_ids, one_by_one=one_by_one)
            attempt = Attempt(round_no, request.seed, result, report, list(stressed),
                              "edit" if editing else "generate", base if editing else None)
            attempts.append(attempt)
            if on_attempt:
                on_attempt(attempt)
        outcome = Outcome(attempts)
        if outcome.ok:
            break
        improved = base is None or attempts.index(outcome.best) != base
        stressed = outcome.best.report.failed
        editing = backend.caps.edit and (repair == "edit" or (repair == "auto" and (improved or not editing)))
    return Outcome(attempts)
