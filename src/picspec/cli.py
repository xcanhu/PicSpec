"""The ``picspec`` command."""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from importlib import resources
from pathlib import Path

from . import __version__
from PIL import Image

from .backends import DEFAULT_BACKEND, Backend, Rendered, Result, make_backend
from .judge import FAIL, NOT_APPLICABLE, PASS, Report, check_image
from .llm import OpenAIChat, make_judge
from .loop import Attempt, generate_checked
from .request import Request, bare_request, build_request
from .spec import SPEC_FILENAME, Spec, SpecError, dumps, find, load, parse_size


class UserError(Exception):
    """A problem the user can fix. Shown without a traceback."""


def _locate(arg: str | None) -> Path:
    if arg:
        p = Path(arg)
        if p.is_dir():
            p = p / SPEC_FILENAME
        if not p.is_file():
            raise UserError(f"{p} does not exist")
        return p
    found = find()
    if found is None:
        raise UserError(f"No {SPEC_FILENAME} here or in any parent folder. Run `picspec init` to create one, "
                        "or pass --spec FILE.")
    return found


def _load(arg: str | None) -> Spec:
    try:
        spec = load(_locate(arg))
    except SpecError as e:
        lines = "\n".join(f"  {p}" for p in e.problems if p.level == "error")
        raise UserError(f"{e.path} has errors:\n{lines}") from e
    return spec


def _size(value: str | None) -> tuple[int, int] | None:
    if value is None:
        return None
    size = parse_size(value)
    if size is None:
        raise UserError(f'--size must look like 1024x1536, not "{value}"')
    return size


def _ids(value: str | None) -> list[str] | None:
    return [s.strip() for s in value.split(",") if s.strip()] if value else None


def _backend(args: argparse.Namespace, spec: Spec | None) -> Backend:
    name = args.backend or (spec.settings.get("backend") if spec else None) or DEFAULT_BACKEND
    if args.workflow and not name.startswith("comfyui"):
        name = "comfyui"
    try:
        return make_backend(name, workflow=args.workflow, base_url=args.base_url, api_key=args.api_key)
    except (ValueError, OSError) as e:
        raise UserError(str(e)) from e


def _request(args: argparse.Namespace, spec: Spec, seed: int = 0) -> Request:
    try:
        return build_request(spec, args.prompt, only=_ids(args.only), skip=_ids(args.skip) or (),
                             size=_size(args.size), quality=args.quality, seed=seed)
    except KeyError as e:
        raise UserError(str(e.args[0])) from e


def _judge(args: argparse.Namespace, spec: Spec) -> OpenAIChat:
    try:
        return make_judge(args.judge or spec.settings.get("judge"), args.judge_base_url, args.judge_api_key)
    except ValueError as e:
        raise UserError(str(e)) from e


_MARK = {PASS: "ok  ", FAIL: "FAIL", NOT_APPLICABLE: "n/a "}


def _print_report(spec: Spec, report: Report) -> None:
    for v in report.verdicts:
        rule = spec.rule(v.rule_id)
        level = "" if rule.level == "must" else "  (should)"
        print(f"  {_MARK.get(v.status, '??  ')} {v.rule_id:<5} {rule.text}{level}")
        if v.seen and v.status != PASS:
            print(f"             {v.seen}")


def _tally(report: Report) -> str:
    met, applied = report.counts
    text = f"{met}/{applied} rules met"
    return text + (f", not met: {', '.join(report.failed)}" if report.failed else "")


def _describe(rendered: Rendered) -> str:
    parts = [rendered.prompt]
    if rendered.negative:
        parts.append(f"[negative] {rendered.negative}")
    for n, ref in enumerate(rendered.references, 1):
        parts.append(f"[reference {n}] {ref.path}  ({ref.rule_id})")
    parts += [f"[note] {note}" for note in rendered.notes]
    return "\n\n".join(parts[:1] + ["\n".join(parts[1:])] if len(parts) > 1 else parts)


# -- commands ---------------------------------------------------------------
def cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.path)
    if target.is_dir() or not target.suffix:
        target = target / SPEC_FILENAME
    if target.exists() and not args.force:
        raise UserError(f"{target} already exists. Pass --force to overwrite it.")
    template = resources.files("picspec").joinpath("templates").joinpath(f"{args.lang}.md").read_text(encoding="utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(template, encoding="utf-8")
    print(f"Wrote {target}. Edit the rules, then run: picspec generate \"your prompt\"")
    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    path = _locate(args.spec)
    spec = load(path, strict=False)
    print(f"{path}: {spec.name or '(no title)'}, {len(spec.rules)} rules")
    for cat in spec.categories:
        if cat.rules:
            print(f"\n{cat.title or '(no section)'}  [{cat.kind}]")
        for r in cat.rules:
            flags = [r.level] + ([f"when: {r.when}"] if r.when else []) + \
                    ([f"{len(r.refs)} ref"] if r.refs else [])
            print(f"  {r.id:<5} {r.text}  ({', '.join(flags)})")
            print(f"        ? {r.question(spec.lang)}  -> {'yes' if r.expected_answer else 'no'}")
    if spec.problems:
        print()
    for p in spec.problems:
        print(p)
    return 1 if spec.errors else 0


def cmd_fmt(args: argparse.Namespace) -> int:
    path = _locate(args.spec)
    spec = load(path, strict=False)
    if spec.errors:
        raise UserError(f"{path} has errors, run `picspec lint` first:\n" +
                        "\n".join(f"  {p}" for p in spec.errors))
    text = dumps(spec)
    if args.check:
        same = path.read_text(encoding="utf-8") == text
        print(f"{path} is {'already formatted' if same else 'not formatted'}")
        return 0 if same else 1
    path.write_text(text, encoding="utf-8")
    print(f"Formatted {path}")
    return 0


def cmd_compile(args: argparse.Namespace) -> int:
    spec = _load(args.spec)
    backend = _backend(args, spec)
    rendered = backend.render(_request(args, spec))
    if args.json:
        print(json.dumps({
            "backend": backend.name, "prompt": rendered.prompt, "negative": rendered.negative,
            "references": [{"path": str(r.path), "rule": r.rule_id, "note": r.note} for r in rendered.references],
            "notes": rendered.notes,
        }, ensure_ascii=False, indent=2))
    else:
        print(_describe(rendered))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    spec = _load(args.spec)
    judge = _judge(args, spec)
    worst = 0
    for name in args.images:
        try:
            with Image.open(name) as im:
                im.load()
                report = check_image(im, spec, judge, only=_only(args, spec), one_by_one=args.one_by_one)
        except (OSError, RuntimeError) as e:
            raise UserError(f"{name}: {e}") from e
        if args.json:
            print(json.dumps({"image": name, "ok": report.ok, "rules": report.to_json()},
                             ensure_ascii=False, indent=2))
        else:
            print(f"{name}: {_tally(report)}")
            _print_report(spec, report)
        worst = max(worst, 0 if report.ok else 1)
    return worst


def _only(args: argparse.Namespace, spec: Spec) -> list[str]:
    """The rule ids left after --only and --skip."""
    try:
        return build_request(spec, "", only=_ids(args.only), skip=_ids(args.skip) or ()).rule_ids
    except KeyError as e:
        raise UserError(str(e.args[0])) from e


def cmd_generate(args: argparse.Namespace) -> int:
    spec = _load(args.spec)
    backend = _backend(args, spec)
    if args.count < 1:
        raise UserError("-n must be at least 1")
    checking = args.check or args.rounds is not None
    judge = _judge(args, spec) if checking else None
    seed = args.seed if args.seed is not None else random.randrange(2**31)
    out = Path(args.out or Path("picspec-out") / time.strftime("%Y%m%d-%H%M%S"))
    out.mkdir(parents=True, exist_ok=True)

    first = _request(args, spec, seed)
    record: dict = {
        "picspec": __version__,
        "prompt": args.prompt,
        "spec": str(spec.path),
        "backend": backend.name,
        "judge": judge.model if judge else None,
        "rules": [{"id": r.id, "text": r.text, "kind": r.kind, "level": r.level, "when": r.when,
                   "question": r.question(spec.lang), "expect": "yes" if r.expected_answer else "no"}
                  for r in spec.rules if r.id in first.rule_ids],
        "images": [],
    }
    for note in backend.render(first).notes:
        print(f"note: {note}", file=sys.stderr)

    def save(result: Result, filename: str, label: str, seed: int, report: Report | None = None,
             **extra: object) -> None:
        result.image.save(out / filename)
        entry = {"file": filename, "kind": label, "seed": seed,
                 "prompt_sent": result.rendered.prompt, "negative_sent": result.rendered.negative,
                 "references": [str(r.path) for r in result.rendered.references], **extra, **result.meta}
        if report is not None:
            entry.update(ok=report.ok, checks=report.to_json())
        record["images"].append(entry)
        took = f", {extra['seconds']}s" if "seconds" in extra else ""
        print(f"{out / filename}  ({label}{': ' + _tally(report) if report is not None else ''}{took})", flush=True)

    exit_code = 0
    try:
        if args.baseline:
            started = time.monotonic()
            result = backend.generate(bare_request(args.prompt, size=first.size, quality=first.quality, seed=seed))
            report = check_image(result.image, spec, judge, only=first.rule_ids,
                                 one_by_one=args.one_by_one) if judge else None
            save(result, "baseline.png", "baseline", seed, report, seconds=round(time.monotonic() - started, 1))
        if judge is None:
            for i in range(args.count):
                started = time.monotonic()
                result = backend.generate(_request(args, spec, seed + i))
                save(result, f"image-{i + 1}.png", "picspec", seed + i, seconds=round(time.monotonic() - started, 1))
        else:
            clock = [time.monotonic()]

            def on_attempt(a: Attempt) -> None:
                n = sum(1 for e in record["images"] if e.get("round") == a.round) + 1
                now = time.monotonic()
                save(a.result, f"round{a.round}-{n}.png", "picspec", a.seed, a.report,
                     round=a.round, stressed=a.stressed, seconds=round(now - clock[0], 1))
                clock[0] = now

            outcome = generate_checked(
                spec, args.prompt, backend, judge, rounds=args.rounds or 3, candidates=args.count, seed=seed,
                only=_ids(args.only), skip=_ids(args.skip) or (), one_by_one=args.one_by_one,
                on_attempt=on_attempt, size=_size(args.size), quality=args.quality)
            best = outcome.best
            best.image.save(out / "best.png")
            record["best"] = next(e["file"] for e in record["images"]
                                  if e.get("round") == best.round and e["seed"] == best.seed)
            print(f"\n{out / 'best.png'}  (copy of {record['best']}: {_tally(best.report)})")
            _print_report(spec, best.report)
            exit_code = 0 if outcome.ok else 1
    except KeyError as e:
        raise UserError(str(e.args[0])) from e
    except (RuntimeError, ValueError, OSError) as e:
        raise UserError(str(e)) from e
    finally:
        (out / "run.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return exit_code


# -- argument parsing -------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="picspec", description="Write down how your images should look, once.")
    parser.add_argument("--version", action="version", version=f"picspec {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help=f"create a starter {SPEC_FILENAME}")
    p.add_argument("path", nargs="?", default=".", help="folder or file to write (default: this folder)")
    p.add_argument("--lang", choices=("zh", "en"), default="en", help="language of the starter file")
    p.add_argument("--force", action="store_true", help="overwrite an existing file")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("lint", help="list the rules and report problems in the spec")
    p.add_argument("spec", nargs="?", help=f"spec file (default: nearest {SPEC_FILENAME})")
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("fmt", help="rewrite the spec in its canonical layout, with rule ids filled in")
    p.add_argument("spec", nargs="?")
    p.add_argument("--check", action="store_true", help="only report whether the file is formatted")
    p.set_defaults(func=cmd_fmt)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("prompt", help="what the image should show")
        p.add_argument("--spec", help=f"spec file (default: nearest {SPEC_FILENAME})")
        p.add_argument("--backend", help=f"gpt-image-2, another images-API model id, comfyui or mock "
                                         f"(default: the spec's backend setting, else {DEFAULT_BACKEND})")
        p.add_argument("--workflow", help="ComfyUI workflow in API format (selects the comfyui backend)")
        p.add_argument("--base-url", help="API base URL, or the ComfyUI address")
        p.add_argument("--api-key", help="API key (default: PICSPEC_OPENAI_API_KEY or OPENAI_API_KEY)")
        p.add_argument("--size", help="WIDTHxHEIGHT (default: the spec's size setting)")
        p.add_argument("--quality", help="low, medium, high or auto (default: the spec's quality setting)")
        p.add_argument("--only", help="apply only these rule ids, comma separated")
        p.add_argument("--skip", help="leave out these rule ids, comma separated")

    def judging(p: argparse.ArgumentParser) -> None:
        p.add_argument("--judge", help="vision model that checks the rules (default: PICSPEC_JUDGE_MODEL, "
                                       "else the spec's judge setting)")
        p.add_argument("--judge-base-url", help="chat API base URL for the judge "
                                                "(default: PICSPEC_JUDGE_BASE_URL, else the OpenAI settings)")
        p.add_argument("--judge-api-key", help="API key for the judge (default: PICSPEC_JUDGE_API_KEY, "
                                               "else the OpenAI key)")
        p.add_argument("--one-by-one", action="store_true",
                       help="ask the judge one rule per request: slower, costs more, less cross-talk")

    p = sub.add_parser("compile", help="show exactly what would be sent to the model, without calling it")
    common(p)
    p.add_argument("--json", action="store_true", help="print JSON")
    p.set_defaults(func=cmd_compile)

    p = sub.add_parser("generate", help="generate images that follow the spec")
    common(p)
    judging(p)
    p.add_argument("--check", action="store_true",
                   help="check every rule on each image and retry with the failed rules stressed")
    p.add_argument("--rounds", type=int, help="most rounds to run when checking (default 3; implies --check)")
    p.add_argument("-n", "--count", type=int, default=1, help="number of images, per round when checking "
                                                              "(default 1)")
    p.add_argument("-o", "--out", help="output folder (default: picspec-out/<time>)")
    p.add_argument("--seed", type=int, help="first seed, for backends that take one")
    p.add_argument("--baseline", action="store_true",
                   help="also generate from the bare prompt, to compare against")
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("check", help="check existing images against the spec, rule by rule")
    p.add_argument("images", nargs="+", help="image files to check")
    p.add_argument("--spec", help=f"spec file (default: nearest {SPEC_FILENAME})")
    p.add_argument("--only", help="check only these rule ids, comma separated")
    p.add_argument("--skip", help="leave out these rule ids, comma separated")
    judging(p)
    p.add_argument("--json", action="store_true", help="print JSON")
    p.set_defaults(func=cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles default to a legacy codepage
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except UserError as e:
        print(f"picspec: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
