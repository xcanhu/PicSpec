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
from .backends import DEFAULT_BACKEND, Backend, Rendered, make_backend
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


def cmd_generate(args: argparse.Namespace) -> int:
    spec = _load(args.spec)
    backend = _backend(args, spec)
    if args.count < 1:
        raise UserError("-n must be at least 1")
    seed = args.seed if args.seed is not None else random.randrange(2**31)
    out = Path(args.out or Path("picspec-out") / time.strftime("%Y%m%d-%H%M%S"))
    out.mkdir(parents=True, exist_ok=True)

    first = _request(args, spec, seed)
    record: dict = {
        "picspec": __version__,
        "prompt": args.prompt,
        "spec": str(spec.path),
        "backend": backend.name,
        "rules": [{"id": r.id, "text": r.text, "kind": r.kind, "level": r.level, "when": r.when,
                   "question": r.question(spec.lang), "expect": "yes" if r.expected_answer else "no"}
                  for r in spec.rules if r.id in first.rule_ids],
        "images": [],
    }
    for note in backend.render(first).notes:
        print(f"note: {note}", file=sys.stderr)

    def run(request: Request, filename: str, label: str) -> None:
        started = time.monotonic()
        result = backend.generate(request)
        result.image.save(out / filename)
        record["images"].append({
            "file": filename, "kind": label, "seed": request.seed,
            "prompt_sent": result.rendered.prompt, "negative_sent": result.rendered.negative,
            "references": [str(r.path) for r in result.rendered.references],
            "seconds": round(time.monotonic() - started, 1), **result.meta,
        })
        print(f"{out / filename}  ({label}, {record['images'][-1]['seconds']}s)")

    try:
        if args.baseline:
            run(bare_request(args.prompt, size=first.size, quality=first.quality, seed=seed),
                "baseline.png", "baseline")
        for i in range(args.count):
            run(_request(args, spec, seed + i), f"image-{i + 1}.png", "picspec")
    except (RuntimeError, ValueError, OSError) as e:
        raise UserError(str(e)) from e
    finally:
        (out / "run.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


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

    p = sub.add_parser("compile", help="show exactly what would be sent to the model, without calling it")
    common(p)
    p.add_argument("--json", action="store_true", help="print JSON")
    p.set_defaults(func=cmd_compile)

    p = sub.add_parser("generate", help="generate images that follow the spec")
    common(p)
    p.add_argument("-n", "--count", type=int, default=1, help="number of images (default 1)")
    p.add_argument("-o", "--out", help="output folder (default: picspec-out/<time>)")
    p.add_argument("--seed", type=int, help="first seed, for backends that take one")
    p.add_argument("--baseline", action="store_true",
                   help="also generate from the bare prompt, to compare against")
    p.set_defaults(func=cmd_generate)
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
