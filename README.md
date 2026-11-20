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

> **Status: v0.4, early.** Working today: the spec format, the gpt-image-2 and ComfyUI adapters, checking each rule on the result with a vision model, and repairing the best image by editing it. Learning rules from your feedback is next: see the [roadmap](#roadmap).

## First live results

Two runs of one prompt, so read this as a smoke test and not as a benchmark. Starter spec (7 rules), gpt-image-2 at 1024x1536, prompt "a young woman with an umbrella in an alley after rain" (given in Chinese).

| Run | Image | Rules met | Not met |
| --- | --- | --- | --- |
| 1 (judge the first judge model) | Bare prompt | 3 of 7 | film grain, waist-up framing, no text in frame, side-back light |
| 1 | With the spec | 6 of 7 | waist-up framing |
| 1 | Generated again, framing stressed | 5 of 7 | waist-up framing, side-back light |
| 2 (judge a vision model) | Bare prompt | 2 of 7 | film grain, facing left, waist-up framing, no text in frame, side-back light |
| 2 | With the spec | 5 of 7 | waist-up framing, side-back light |
| 2 | Edit of the image above | 4 of 7 | film grain, waist-up framing, side-back light |
| 2 | Generated again, both stressed | 6 of 7 | waist-up framing |

What this shows so far:

- Applying the spec moved the bare prompt from 2 or 3 rules met to 5 or 6.
- The waist-up framing rule failed in all seven images, whether stressed or edited. Prompt wording alone does not move this model on it.
- The one edit repair made things worse: asked to fix two rules while keeping the rest, it fixed neither, lost the grain and shifted the colours. Editing one rule at a time, and cropping for framing rules, are the next things to try.
- The judges were consistent: a vision model agreed with the first judge model on 20 of 21 verdicts on the run 1 images, and a person agreed with the judge on the bare-prompt and best images of both runs. Asking one rule per request flipped one more verdict, on skin texture.
- Each image took 45 to 65 seconds including its check. The ComfyUI adapter has not been run against a live server yet.

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

To have every rule checked, name a vision model and add `--check`:

```bash
export PICSPEC_JUDGE_MODEL=your-vision-model     # any model that reads images over an OpenAI-style chat API
picspec generate "a woman with an umbrella in an alley after rain" --check --baseline
picspec check photo.png                          # check an image you already have
```

| Command | What it does |
| --- | --- |
| `picspec init [path]` | Create a starter `PICSPEC.md` |
| `picspec lint [spec]` | List every rule with its check question; report errors with line numbers |
| `picspec fmt [spec]` | Rewrite the file in its standard layout and give every rule an id |
| `picspec compile "prompt"` | Print the exact prompt, negative prompt and reference images for a backend |
| `picspec generate "prompt"` | Generate images that follow the spec |
| `picspec generate "prompt" --check` | Generate, check every rule, and repair what failed |
| `picspec check image.png` | Check existing images against the spec, rule by rule |
| `picspec audit image.png --probe ...` | Test the judge: change images in known ways and see whether its answers follow |

`compile` and `generate` take `--only t1,c1` and `--skip f2` to choose rules, `--size 1536x1024`, `--quality high`, and `--spec FILE`. Without `--spec`, PicSpec uses the `PICSPEC.md` in the current folder or the nearest parent folder, so one spec can cover a whole project.

## Checking and retrying

With `--check`, each finished image goes to a vision model together with the check question of every rule in use. For each rule the model first says what it sees, then answers yes or no, or "not applicable" when the rule's `when` condition is not true for this image. An answer that matches the rule's `expect` means the rule was met.

```
picspec-out/20261120-121500/round1-1.png  (picspec: 5/7 rules met, not met: t1, c1)
picspec-out/20261120-121500/round2-1.png  (picspec: 7/7 rules met)

picspec-out/20261120-121500/best.png  (copy of round2-1.png: 7/7 rules met)
```

- An image passes when every `must` rule that applies is met. `should` rules are reported and stressed on a retry, but do not fail an image.
- When no image in a round passes, the next round repairs the best image so far: it is sent to the model's edit endpoint with an instruction that lists what to fix and what is already right and must stay. Every rule is checked again afterwards, so a repair that breaks something else does not win.
- Backends that cannot edit (ComfyUI for now) generate again instead, with the failed rules at the top of the prompt, marked as most important. `--repair regenerate` forces this, `--repair edit` always edits, and the default `--repair auto` edits and switches to generating again after a round of edits that made nothing better.
- `--rounds N` sets the most rounds to run (default 3). `-n K` generates K images per round. The loop stops at the first round with a passing image, and `best.png` is the image with the fewest failed rules.
- `--one-by-one` sends one request per rule instead of one per image. It costs more and stops one answer from colouring the next.
- For images larger than 1536 pixels on a side, look rules such as grain and sharpness also get a full-resolution crop from the centre, because that detail disappears when the whole image is scaled down.
- `run.json` records every image, the prompt that was sent, and each rule's verdict with what the model saw.

The judge is set with `--judge MODEL`, the `PICSPEC_JUDGE_MODEL` variable, or a `judge:` line in the spec's settings. Its address and key come from `--judge-base-url` and `--judge-api-key`, then `PICSPEC_JUDGE_BASE_URL` and `PICSPEC_JUDGE_API_KEY`, then the OpenAI settings. The command exits with 1 when the best image still fails a `must` rule.

Cost: one checked image is one image request plus one vision request. Three rounds of two images is at most six of each.

## Auditing the judge without human labels

Every result above rests on the judge being right, so PicSpec can test the judge itself. `picspec audit` changes an image in a way that makes the right answer known, asks the judge again, and counts how often its answer follows.

```bash
picspec audit photo1.png photo2.png \
    --probe flip=c1 --probe text=f2 --probe grain=t1 --probe blur=t2 --probe smooth=f1 -o audit-out
```

| Probe | What it does to the image | What the named rule's answer must do |
| --- | --- | --- |
| `flip` | Mirrors it | A "yes" to a left/right question must become "no"; every other rule must keep its answer |
| `text` | Draws a line of text | Become "yes" |
| `grain` | Adds noise at three strengths | Become "yes" at the strongest; the weaker levels show where the judge starts to notice |
| `blur` | Blurs at three strengths | Become "no" at the strongest |
| `smooth` | Flattens fine texture | Become "yes" |

Write `--probe smooth=t1:no` when the rule's question runs the other way (smoothing must make "is grain visible?" a no). Each original is also asked about twice, which measures how often the judge contradicts itself. The output gives one line per probe and rule, such as `grain t1 6/7 correct`, and `-o` saves the changed images and every answer. These probes test whether the judge can see a property, not whether a person would like the result, and they do not cover framing or light direction yet.

A first live audit (7 generated images, 84 vision requests, one judge model):

| Probe | Rule | Result |
| --- | --- | --- |
| `flip` | faces left | 6/6 correct (the seventh image had no "yes" to invert) |
| `text` | no text | 7/7 |
| `grain` | visible grain | 7/7 at every strength, including the weakest, which a person only sees when zoomed in |
| `blur` | sharp face | 7/7 at every strength |
| `smooth` | no grain left | 7/7 |
| `smooth` | plastic skin | 2/7 at the weak level, 5/7 at the strong one |

Asked twice about an unchanged image, the judge repeated 48 of 49 answers. After mirroring, 37 of 42 answers on rules that should not care about direction stayed the same. Two lessons: the judge calls grain "visible" below the level a person notices at normal viewing size, and the `smooth` probe is a poor test of over-retouched skin, because it smears the whole frame instead of only the skin, so the judge's "no" is often defensible.

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

- **Settings** (optional) sit between `---` lines at the top: `size`, `quality`, `backend`, `judge`, `lang` (`en` or `zh`).
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

1. **Spec format and adapters.** Done.
2. **Check and repair.** Done. Next here: measure how often the judge agrees with people, and compare editing against generating again.
3. **Learn from feedback.** Say "the face is too blurry" and PicSpec proposes a new or changed rule for you to approve.
4. **More ways to use it.** MCP server, ComfyUI node, reference images for local models, before/after galleries.
5. **Benchmark.** How well image models follow fine-grained look instructions such as grain, sharpness and motion direction.

## License

Apache-2.0
