# PicSpec

**Write down how your images should look, once. Every image model follows it, and every rule gets checked.**

[中文说明](README.zh-CN.md)

You know the look you want: a little film grain, a sharp face, the subject walking left, never that plastic skin. Today you retype it into every prompt, and the model still forgets half of it. PicSpec keeps those preferences in one file, `PICSPEC.md`, as rules that can each be checked with a yes or no question. It adds them to every prompt in the way each model understands best, for commercial models (gpt-image-2) and local ones (ComfyUI) alike. No model is trained or fine-tuned.

```markdown
# My image spec

Natural-light documentary portraits with the look of 35mm film.

## Image look
- `t1` Fine film grain across the whole frame, no digital smoothness
  - check: Is an even, fine grain visible across the image?
- `t2` The face is sharp and the eyes are in focus
  - check: Are the person's eyes and face sharp, with no blur?
  - when: there is a person in the image

## Subject and composition
- `c1` The person faces or walks toward the left of the frame
  - check: Does the person face or move toward the left of the frame?
  - ref: refs/pose-left.jpg | body direction like this

## Avoid
- `f1` Over-smoothed, plastic-looking skin
  - check: Does the skin look over-smoothed or plastic?
  - expect: no
```

> **Status: v0.1, early.** The spec format, the backend interface, the gpt-image-2 and ComfyUI adapters and the CLI work today. Checking each rule against the result and learning rules from your feedback are next: see the [roadmap](#roadmap). The gpt-image-2 adapter is tested against a local stand-in for the API and has not yet been run against the live service.

## Install

```bash
git clone https://github.com/xcanhu/PicSpec && cd PicSpec
pip install -e .
```

Python 3.10 or newer. The only dependency is Pillow.

## Quick start

```bash
picspec init                       # writes a starter PICSPEC.md (add --lang zh for Chinese)
picspec lint                       # lists the rules and reports mistakes in the file
picspec compile "a woman with an umbrella in an alley after rain"   # shows what would be sent; calls nothing

export OPENAI_API_KEY=sk-...
picspec generate "a woman with an umbrella in an alley after rain" --baseline -n 2
```

`generate` writes the images and a `run.json` record into `picspec-out/<time>/`. With `--baseline` it also generates from the bare prompt, so you can compare the two side by side.

| Command | What it does |
| --- | --- |
| `picspec init [path]` | Create a starter `PICSPEC.md` |
| `picspec lint [spec]` | List every rule with its check question; report errors with line numbers |
| `picspec fmt [spec]` | Rewrite the file in its standard layout and give every rule an id |
| `picspec compile "prompt"` | Print the exact prompt, negative prompt and reference images for a backend |
| `picspec generate "prompt"` | Generate images that follow the spec |

`compile` and `generate` take `--only t1,c1` and `--skip f2` to choose rules, `--size 1536x1024`, `--quality high`, and `--spec FILE`. Without `--spec`, PicSpec uses the `PICSPEC.md` in the current folder or the nearest parent folder, so one spec can cover a whole project.

## Backends

| Backend | How to select it | Reference images | Negative prompt | Seed |
| --- | --- | --- | --- | --- |
| gpt-image-2 (default) | `--backend gpt-image-2` | up to 16 | no | no |
| Any model behind an OpenAI-style images API | `--backend MODEL --base-url URL` | up to 16 | no | no |
| ComfyUI (local) | `--workflow workflow_api.json` | not yet | if the workflow has `%negative%` | if the workflow has `%seed%` |
| mock | `--backend mock` | 4 | yes | yes |

**gpt-image-2.** The key comes from `--api-key`, `PICSPEC_OPENAI_API_KEY` or `OPENAI_API_KEY`; the address from `--base-url`, `PICSPEC_OPENAI_BASE_URL` or `OPENAI_BASE_URL`, so API gateways work too. When the rules in use carry reference images, the request goes to the edits endpoint with the images attached, and the prompt says which aspect of each image to follow. Sizes are checked before anything is sent: both sides divisible by 16, aspect ratio between 1:3 and 3:1, at most 3840x2160.

**ComfyUI.** Start ComfyUI, export your workflow with "Save (API Format)", and put the placeholders `%prompt%`, and optionally `%negative%`, `%seed%`, `%width%`, `%height%`, where those values go. [examples/comfyui](examples/comfyui) has Qwen-Image GGUF workflows that fit an 8 GB card. The address defaults to `http://127.0.0.1:8188`; change it with `--base-url` or `PICSPEC_COMFYUI_URL`. Local models get the rules as one plain paragraph, which their text encoders handle better than lists. The two example workflows set CFG to 1 for speed, and at that setting a negative prompt has no effect.

**mock** draws a flat colour. Use it to try the commands without a key or a GPU.

## The PICSPEC.md format

A spec is plain Markdown that reads well on GitHub and is easy to edit by hand.

- **Settings** (optional) sit between `---` lines at the top: `size`, `quality`, `backend`, `lang` (`en` or `zh`).
- **The paragraph under the title** describes the overall style. It is sent with every prompt.
- **Each `##` section** groups rules. The heading decides the kind of its rules: headings about look, quality, light or colour are *image look*; headings about subject, composition or pose are *subject and composition*; headings with "avoid", "never" or "forbidden" are *avoid*. Any other heading is a general section.
- **Each top-level bullet is one rule.** The optional name in backticks is its id; `picspec fmt` fills in missing ids.
- **Indented bullets are the rule's fields:**

| Field | Meaning | Default |
| --- | --- | --- |
| `check` | A yes/no question about the finished image that decides whether the rule was met | A generic question built from the rule text |
| `expect` | The answer that means "met": `yes` or `no` | `yes` |
| `level` | `must`, or `should` for nice-to-have rules | `must` |
| `when` | When the rule applies, for example "there is a person in the image" | Always |
| `prompt` | Wording to send to the model instead of the rule text | The rule text |
| `negative` | Terms for the negative prompt, on backends that have one | None |
| `ref` | A reference image, as `path \| what to take from it`. Repeat the line for more images | None |
| `kind` | Overrides the kind taken from the heading: `texture`, `composition`, `forbid`, `other` | From the heading |

Rules in an *avoid* section name the unwanted thing itself ("Text, watermarks or logos"), their check asks whether it is present, and `expect` is `no`. `picspec lint` warns when this looks reversed.

Field names can also be written in Chinese (`核对`, `期望`, `级别`, `适用`, `提示词`, `反向`, `参考图`, `类型`). Comments, quotes and code blocks are kept as notes and never read as rules. See [examples](examples) for complete files.

## Use it from Python

```python
from picspec import load, build_request
from picspec.backends import make_backend

spec = load("PICSPEC.md")
request = build_request(spec, "a woman with an umbrella in an alley after rain")
backend = make_backend("gpt-image-2")
print(backend.render(request).prompt)      # what will be sent
result = backend.generate(request)
result.image.save("out.png")
```

A backend is a small class: it declares what it supports (reference images, negative prompt, seed), turns a request into its model's own wording in `render`, and makes the image in `_run`. See [src/picspec/backends](src/picspec/backends).

## Roadmap

1. **Spec format and adapters.** Done in v0.1: this release.
2. **Check and retry.** A vision model answers each rule's question about the result; only the rules that failed are stressed in the next attempt.
3. **Learn from feedback.** Say "the face is too blurry" and PicSpec proposes a new or changed rule for you to approve.
4. **More ways to use it.** MCP server, ComfyUI node, reference images for local models, before/after galleries.
5. **Benchmark.** How well image models follow fine-grained look instructions such as grain, sharpness and motion direction.

## License

Apache-2.0
