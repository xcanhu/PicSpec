"""Measure what a spec changes, over many prompts.

For each prompt: one image from the bare prompt, one with the spec applied, and, when repair rounds
are allowed, the best image after repair. Every image is checked against every rule. The result is a
table of how often each rule is met in each condition, which is the evidence a single before/after
picture cannot give.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from .backends.base import Backend
from .judge import NOT_APPLICABLE, PASS, Report, check_image
from .llm import ChatModel
from .loop import generate_checked
from .request import bare_request, build_request
from .spec import Spec

CONDITIONS = ("bare", "spec", "repaired")


def read_prompts(path: str | Path) -> list[str]:
    """One prompt per line. Blank lines and lines starting with # are skipped."""
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    return [s.strip() for s in lines if s.strip() and not s.strip().startswith("#")]


def _row(report: Report) -> dict[str, str]:
    return {v.rule_id: v.status for v in report.verdicts}


def run(spec: Spec, prompts: list[str], backend: Backend, judge: ChatModel, out: Path, *, rounds: int = 1,
        seed: int = 0, faces: Any = "auto", on_step: Callable[[str], None] | None = None,
        **request_options: Any) -> dict[str, Any]:
    """Generate and check. Results are saved after every prompt, and prompts already in
    ``out/bench.json`` are not run again, so an interrupted run can be continued."""
    out.mkdir(parents=True, exist_ok=True)
    store = out / "bench.json"
    data: dict[str, Any] = {"spec": str(spec.path), "backend": backend.name, "judge": getattr(judge, "model", ""),
                            "rounds": rounds, "items": []}
    if store.is_file():
        data = json.loads(store.read_text(encoding="utf-8"))
    done = {item["prompt"] for item in data["items"]}
    say = on_step or (lambda _: None)
    for n, prompt in enumerate(prompts, 1):
        if prompt in done:
            continue
        item: dict[str, Any] = {"prompt": prompt, "n": n}
        started = time.monotonic()
        first = build_request(spec, prompt, seed=seed + n, **request_options)
        say(f"[{n}/{len(prompts)}] bare: {prompt}")
        bare = backend.generate(bare_request(prompt, size=first.size, quality=first.quality, seed=seed + n))
        bare.image.save(out / f"{n:03d}-bare.png")
        item["bare"] = _row(check_image(bare.image, spec, judge, faces=faces))
        say(f"[{n}/{len(prompts)}] spec")
        outcome = generate_checked(spec, prompt, backend, judge, rounds=rounds, seed=seed + n, faces=faces,
                                   **request_options)
        outcome.attempts[0].image.save(out / f"{n:03d}-spec.png")
        item["spec"] = _row(outcome.attempts[0].report)
        if len(outcome.attempts) > 1:
            best = outcome.best
            best.image.save(out / f"{n:03d}-repaired.png")
            item["repaired"] = _row(best.report)
            item["repair"] = [a.method for a in outcome.attempts[1:]]
            item["best_method"] = best.method
        elif rounds > 1:
            item["repaired"] = item["spec"]  # nothing needed repair
        item["image_requests"] = 1 + sum(a.method != "fix" for a in outcome.attempts)
        item["seconds"] = round(time.monotonic() - started, 1)
        data["items"].append(item)
        store.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def summarise(data: dict[str, Any], spec: Spec) -> dict[str, Any]:
    """Per rule and per condition: [times met, times it applied]. Plus the same over all rules, and
    how many images met every must-level rule."""
    conditions = [c for c in CONDITIONS if any(c in item for item in data["items"])]
    rules: dict[str, dict[str, list[int]]] = {r.id: {c: [0, 0] for c in conditions} for r in spec.rules}
    whole = {c: [0, 0] for c in conditions}
    for item in data["items"]:
        for c in conditions:
            row = item.get(c)
            if row is None:
                continue
            ok = True
            for r in spec.rules:
                status = row.get(r.id)
                if status is None or status == NOT_APPLICABLE:
                    continue
                rules[r.id][c][1] += 1
                rules[r.id][c][0] += status == PASS
                ok = ok and (status == PASS or r.level != "must")
            whole[c][1] += 1
            whole[c][0] += ok
    total = {c: [sum(v[c][0] for v in rules.values()), sum(v[c][1] for v in rules.values())] for c in conditions}
    return {"conditions": conditions, "prompts": len(data["items"]), "rules": rules, "all_rules": total,
            "images_meeting_every_must_rule": whole,
            "image_requests": sum(item.get("image_requests", 0) for item in data["items"])}


def _cell(pair: list[int]) -> str:
    return f"{pair[0]}/{pair[1]} ({pair[0] / pair[1]:.0%})" if pair[1] else "n/a"


def to_markdown(summary: dict[str, Any], spec: Spec, lang: str = "en") -> str:
    zh = lang == "zh"
    names = {"bare": "裸提示词" if zh else "Bare prompt", "spec": "带规格" if zh else "With spec",
             "repaired": "修复后" if zh else "After repair"}
    conditions = summary["conditions"]
    lines = ["| " + " | ".join([("规则" if zh else "Rule"), *(names[c] for c in conditions)]) + " |",
             "| " + " | ".join(["---"] * (len(conditions) + 1)) + " |"]
    measured = False
    for r in spec.rules:
        mark = " †" if r.measurement else ""
        measured = measured or bool(mark)
        lines.append(f"| `{r.id}` {r.text}{mark} | "
                     + " | ".join(_cell(summary["rules"][r.id][c]) for c in conditions) + " |")
    lines.append(f"| **{'全部规则' if zh else 'All rules'}** | "
                 + " | ".join(_cell(summary["all_rules"][c]) for c in conditions) + " |")
    lines.append(f"| **{'所有必须项都满足的图' if zh else 'Images meeting every must rule'}** | "
                 + " | ".join(_cell(summary["images_meeting_every_must_rule"][c]) for c in conditions) + " |")
    notes = ["一条规则对某张图不适用时，不计入它的分母。" if zh else
             "A rule that does not apply to an image is left out of that rule's count."]
    if measured:
        notes.append("† 这条规则由测量判定（装了所需工具时），不是由判官判定；修复后的数字用的是同一个测量，"
                     "说明修复达到了测量目标，不代表人看起来一定更好。" if zh else
                     "† Decided by a measurement (when its tool is installed), not by the judge. The figure after "
                     "repair uses the same measurement: it shows the repair hit its target, not that a person "
                     "would prefer the result.")
    return "\n".join(lines) + "\n\n" + "\n".join(notes) + "\n"
