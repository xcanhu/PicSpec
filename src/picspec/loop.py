"""Generate, check every rule, and try again with the failed rules stressed."""

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
    on_attempt: Callable[[Attempt], None] | None = None,
    **request_options: Any,
) -> Outcome:
    """Run up to ``rounds`` rounds of ``candidates`` images each.

    A round stops the loop as soon as one image meets every must-level rule. Otherwise the
    next round stresses the rules that the best image so far failed.
    """
    only_ids = list(only) if only is not None else None
    skip_ids = list(skip)
    attempts: list[Attempt] = []
    stressed: list[str] = []
    for round_no in range(1, max(rounds, 1) + 1):
        for _ in range(max(candidates, 1)):
            request = build_request(spec, prompt, only=only_ids, skip=skip_ids, emphasize=stressed,
                                    seed=seed + len(attempts), **request_options)
            result = backend.generate(request)
            report = check_image(result.image, spec, judge, only=request.rule_ids, one_by_one=one_by_one)
            attempt = Attempt(round_no, request.seed, result, report, list(stressed))
            attempts.append(attempt)
            if on_attempt:
                on_attempt(attempt)
        outcome = Outcome(attempts)
        if outcome.ok:
            break
        stressed = outcome.best.report.failed
    return Outcome(attempts)
