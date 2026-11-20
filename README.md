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

> **Status: v0.7, early.** Working today: the spec format, the gpt-image-2 and ComfyUI adapters, checking each rule on the result with a vision model, and repairing the best image by editing it. Learning rules from your feedback is next: see the [roadmap](#roadmap).

## Gallery

Real outputs from the runs below: the same prompt with no spec, with the starter spec, and after repair in code. Counts are rules met as checked by the tool.

| Prompt | Bare prompt | With spec | After repair |
| --- | --- | --- | --- |
| A woman with an umbrella in an alley after rain | <img src="docs/gallery/01-bare.jpg" width="220"><br>2 of 6 | <img src="docs/gallery/01-spec.jpg" width="220"><br>4 of 7 | <img src="docs/gallery/01-repaired.jpg" width="220"><br>6 of 7 |
| A commuter waiting on a subway platform | <img src="docs/gallery/02-bare.jpg" width="220"><br>1 of 7 | <img src="docs/gallery/02-spec.jpg" width="220"><br>4 of 7 | <img src="docs/gallery/02-repaired.jpg" width="220"><br>6 of 7 |
| A middle-aged man repairing a bicycle | <img src="docs/gallery/03-bare.jpg" width="220"><br>2 of 7 | <img src="docs/gallery/03-spec.jpg" width="220"><br>5 of 7 | <img src="docs/gallery/03-repaired.jpg" width="220"><br>6 of 7 |

A short drama: a character sheet and a setting, then two keyframes that use both as references.

| Character sheet | Setting | Keyframe 1 | Keyframe 2 |
| --- | --- | --- | --- |
| <img src="docs/gallery/drama-character.jpg" width="170"> | <img src="docs/gallery/drama-scene.jpg" width="230"> | <img src="docs/gallery/drama-shot1.jpg" width="170"> | <img src="docs/gallery/drama-shot2.jpg" width="170"> |

## Live results

**Ten prompts, bare against spec.** Ten different scenes with a person (cafe, kitchen, subway, flower shop, snow, library, night market, mountain top, seaside, basketball court), one image each way, starter spec of 7 rules, gpt-image-2 at medium quality, one round, no repair, judged by a vision model.

| Rule | Bare prompt | With the spec |
| --- | --- | --- |
| Film grain | 0/10 | 10/10 |
| Sharp face | 8/10 | 10/10 |
| Side-back light (should) | 2/10 | 2/10 |
| Faces left | 5/10 | 10/10 |
| Waist-up framing | 2/10 | 5/10 |
| No plastic skin | 10/10 | 10/10 |
| No text or logos | 3/10 | 9/10 |
| **All rules** | **30/70 (43%)** | **56/70 (80%)** |

The spec image met more rules than the bare one for all ten prompts. Read the rows with the judge's reliability in mind: grain, direction and text are rules the judge was verified on, so those gains are solid. The plastic-skin row is not a result, because the judge cannot see that problem. Light direction did not move at all, and framing moved only halfway, which is why framing is now repaired by cropping. One image per prompt per condition, one model, one judge.

### The first smoke test

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
| `picspec init [path] [--template NAME]` | Create a starter `PICSPEC.md` |
| `picspec rules [id ...]` | Browse the rule library, or print rules to paste into a spec |
| `picspec lint [spec]` | List every rule with its check question; report errors with line numbers |
| `picspec fmt [spec]` | Rewrite the file in its standard layout and give every rule an id |
| `picspec compile "prompt"` | Print the exact prompt, negative prompt and reference images for a backend |
| `picspec generate "prompt"` | Generate images that follow the spec |
| `picspec generate "prompt" --check` | Generate, check every rule, and repair what failed |
| `picspec check image.png` | Check existing images against the spec, rule by rule |
| `picspec learn "feedback"` | Turn a sentence of feedback into a proposed rule change |
| `picspec bench prompts.txt` | Bare prompt against spec over many prompts, with per-rule pass rates |
| `picspec mcp` | Run as an MCP server for coding agents |
| `picspec faces a.png b.png` | Find faces and compare them pairwise (needs the face tools) |
| `picspec audit image.png --probe ...` | Test the judge: change images in known ways and see whether its answers follow |

`compile` and `generate` take `--only t1,c1` and `--skip f2` to choose rules, `--size 1536x1024`, `--quality high`, and `--spec FILE`. Without `--spec`, PicSpec uses the `PICSPEC.md` in the current folder or the nearest parent folder, so one spec can cover a whole project.

## Rule library and starter specs

People want different things from generated images, so PicSpec ships a library of ready-made rules, grouped by what users ask for and complain about most:

| Category | Examples | Rules |
| --- | --- | --- |
| Realism and texture | skin pores, film grain, no plastic skin, no oversaturation | 7 |
| Expression and presence | natural expression, catchlight in the eyes, no staged smile | 6 |
| Structure and physical defects | hands, limbs, warped objects, broken architecture | 7 |
| Text in the image | no text, no overlaid captions, legible text | 3 |
| Light, composition and lens | sharp face, shot size, facing direction, plain background | 18 |
| Style and tone | photoreal, flat illustration, limited palette, no render look | 7 |
| Consistency with a reference image | same face, same outfit, same place, same style | 5 |

```bash
picspec rules                          # list everything
picspec rules --category expression    # one category
picspec rules skin-texture bad-hands   # print these as spec text, ready to paste
```

Every entry carries an honest label for how far a vision model can be trusted to check it: **judge verified** (the judge followed synthetic changes in a live test: 6 rules so far), **judge unreliable** (it failed one: plastic skin, skin texture, same face), or **untested** (everything else). An untested rule still shapes the prompt; treat its pass or fail as a hint until it has been audited.

`picspec init --template NAME` writes a starter spec built from the library:

| Template | For |
| --- | --- |
| `starter` (default) | A film-look documentary portrait, the example at the top of this page |
| `portrait` | Realistic portraits: skin texture, natural expression, no beautified faces |
| `product` | Shop listing photos: whole product, plain background, no colour cast |
| `illustration` | Flat illustration: limited palette, clean lines, no photographic shading |
| `drama-character` | AI short drama character sheet: one character, full body, neutral pose, plain background |
| `drama-scene` | AI short drama setting or building: wide empty shot, straight verticals, no broken architecture |
| `drama-shot` | AI short drama keyframe (9:16): face, outfit, setting, light and style must match your reference images |

### Consistency across images

A rule that has a `ref` image is checked against that image: the judge receives the reference next to the result, so a question such as "Is the person's face the same person as in the reference image?" works. The `drama-shot` template expects `refs/character.png` and `refs/scene.png` next to the spec, which you make first with the other two drama templates. Face drift between shots is the complaint that production guides for AI short dramas raise most often; these comparison rules are new. In a first trial of 7 image pairs the judge was right on every pair that really matched, but called 3 of 3 different generated faces the same person, so treat a pass on `same-face` with caution. Install the [face tools](#face-tools-optional) to have a face-comparison model decide it instead.

## Face tools (optional)

Two things a vision model does badly on portraits are measured instead when you install the face tools:

```bash
pip install -e ".[face]"     # OpenCV; two small models download on first use
picspec faces a.png b.png    # faces found, and how alike each pair is
```

- **Skin and expression.** In a 1024x1536 image the face is too small for the judge to see pores: it answered "no visible skin texture" on every test image, retouched or not. With the face tools, the judge also receives a full-resolution close-up of the main face whenever the face is under 40% of the image height.
- **Same person.** A rule with `measure: face-match` and a `ref` image is decided by a face-comparison model (cosine similarity of SFace embeddings), not by the judge. The score must reach 0.6 by default; set your own with `measure: face-match >= 0.5`. Give the rule several `ref` lines (front, three-quarter view, profile) and the closest one counts. A face turned too far to compare makes the rule not applicable.

A first live run (7 generated portraits, faces 7% to 17% of the image height):

| Question | Result |
| --- | --- |
| Does SFace's published threshold of 0.363 separate generated faces? | No. 15 of 20 unrelated generated portraits scored 0.363 or more. They ranged from 0.22 to 0.61 |
| Does a higher one? | Mostly. 62 of 63 lightly altered copies of the same face (mirror, crop, light blur, light grain, retouching) scored above 0.62. Heavy blur or grain pulls the same face down to 0.30, so no threshold is perfect |
| Does the close-up help "are pores visible"? | Yes. Without it 0 of 7 originals passed; with it 4 of 7 passed, and most of their smoothed copies failed |
| Does it help "is the skin plastic"? | Hardly. The judge still missed most smoothed faces and changed its mind between runs |

PicSpec therefore uses 0.6. Treat that number as a starting point: it comes from one small set of images, and it is strict on turned heads (see the short drama run below).

Without the face tools everything still works: measured rules fall back to the judge and the command says so. Set `PICSPEC_FACE=off` to turn them off, or `PICSPEC_FACE_MODELS` to a folder holding the model files if the machine is offline.

### A short drama, end to end

One live run with the three drama templates: a character sheet, a setting, then three 9:16 keyframes that take both as reference images (5 image requests, about two minutes each at high quality).

| Keyframe | Rules met | Face similarity to the sheet | Looking at the image |
| --- | --- | --- | --- |
| She walks into the lane, seen from the front | 9 of 9 | 0.75, pass | Same woman, same lane |
| She looks back over her shoulder | 8 of 9 | 0.54, fail | Same woman, same lane: the tool was wrong |
| Seen from behind, at a door | 7 of 9 | 0.29, fail | Same hair and coat; the face is barely visible |

gpt-image-2 kept the character, her outfit, the lane and the style in all three, and the judge agreed on outfit, place, style and light. The face comparison was the weak part: it is strict on a head turned three-quarters, and it scored a sliver of a profile that should not have been scored. Since this run, a face in profile makes the rule not applicable, and a rule can take several reference views; neither change has been tried on live images yet.

## Measured rules and repairs in code

A vision model is not the right tool for everything. A rule with a `measure` field is decided by a measurement instead, which costs nothing and gives the same answer every time:

| Measure | What it measures | Example | Needs |
| --- | --- | --- | --- |
| `grain` | Fine noise in the flat areas of the image, 0 to 255. About 3 is faint grain seen when zoomed in, 5 shows on a close look, 10 is obvious | `measure: grain >= 3` | nothing |
| `face-share` | Height of the main face as a share of the image height. This is the shot size: about 0.06 to 0.13 is a full body, 0.16 to 0.32 is waist-up | `measure: face-share 0.16..0.32` | face tools |
| `face-match` | Similarity between the face and the rule's `ref` image | `measure: face-match >= 0.6` | face tools |

Two of these can also be **repaired in code**, before PicSpec pays for an edit or a new image. If the face is too small for the framing rule, the image is cropped around it and enlarged back to size (up to 2x). If grain is missing, it is added. The repaired image is checked again like any other and shows up as `fixed in code from round1-1.png`. Shot size is the case this was built for: across our tests gpt-image-2 followed "waist-up" in fewer than half the images, however the prompt was worded.

On four real images that failed framing or grain, three were cropped (enlarged 1.3x to 1.7x) and regrained, and came out as sensible waist-up frames that stayed acceptably sharp; the fourth needed more than 2x and was left uncropped, as designed. How far to trust the thresholds: the grain level matched the judge on all 42 audit images at 2.6, but disagreed with it on 8 of 20 fresh images, because levels between 2 and 3 are below what an eye separates at normal size. A face share under 0.15 was judged "too wide" every time, while 0.15 to 0.20 was a coin toss for the judge, and a first default of 0.22 turned out too strict: it cropped a frame that was already a good waist-up shot at 0.17. The default is now 0.16, and a crop aims for 0.20. Both defaults rest on a few dozen images.

## Checking and retrying

With `--check`, each finished image goes to a vision model together with the check question of every rule in use. For each rule the model first says what it sees, then answers yes or no, or "not applicable" when the rule's `when` condition is not true for this image. An answer that matches the rule's `expect` means the rule was met.

```
picspec-out/20261120-121500/round1-1.png  (picspec: 5/7 rules met, not met: t1, c1)
picspec-out/20261120-121500/round2-1.png  (picspec: 7/7 rules met)

picspec-out/20261120-121500/best.png  (copy of round2-1.png: 7/7 rules met)
```

- An image passes when every `must` rule that applies is met. `should` rules are reported and stressed on a retry, but do not fail an image.
- Failures that code can repair (shot size, grain) are repaired first, at no image cost. See [measured rules](#measured-rules-and-repairs-in-code).
- When no image in a round passes, the next round repairs the best image so far: it is sent to the model's edit endpoint with an instruction that lists what to fix and what is already right and must stay. Every rule is checked again afterwards, so a repair that breaks something else does not win.
- Backends that cannot edit (ComfyUI for now) generate again instead, with the failed rules at the top of the prompt, marked as most important. `--repair regenerate` forces this, `--repair edit` always edits, and the default `--repair auto` edits and switches to generating again after a round of edits that made nothing better.
- `--rounds N` sets the most rounds to run (default 3). `-n K` generates K images per round. The loop stops at the first round with a passing image, and `best.png` is the image with the fewest failed rules.
- `--one-by-one` sends one request per rule instead of one per image. It costs more and stops one answer from colouring the next.
- For images larger than 1536 pixels on a side, look rules such as grain and sharpness also get a full-resolution crop from the centre, because that detail disappears when the whole image is scaled down.
- `run.json` records every image, the prompt that was sent, and each rule's verdict with what the model saw.

The judge is set with `--judge MODEL`, the `PICSPEC_JUDGE_MODEL` variable, or a `judge:` line in the spec's settings. Its address and key come from `--judge-base-url` and `--judge-api-key`, then `PICSPEC_JUDGE_BASE_URL` and `PICSPEC_JUDGE_API_KEY`, then the OpenAI settings. The command exits with 1 when the best image still fails a `must` rule.

Cost: one checked image is one image request plus one vision request. Three rounds of two images is at most six of each.

## Learning rules from feedback

When a result is wrong, say why once, and it becomes a rule:

```bash
picspec learn "the skin is too smooth, like a beauty filter" --image out/best.png
```

```
add    plastic-skin: the complaint is about over-retouched skin
add    skin-texture: asks for visible skin detail

+- `skin-texture` Skin keeps its natural texture: visible pores and small imperfections
+  - check: Can you see pores or fine texture on the skin?
...
Run `picspec learn --apply` to write exactly this change to the spec.
```

A chat model reads your spec, the rule library and the feedback, then proposes the smallest change: tighten an existing rule, add a library rule, write a new one, or remove one. Nothing is written until you run `picspec learn --apply`, which writes the change you were shown without asking the model again. Feedback about one picture's content ("make her smile in this one") produces no rule. The model is the same one that checks images (`--judge`, `PICSPEC_JUDGE_MODEL`).

## Agents and ComfyUI

**MCP server.** `picspec mcp` speaks the Model Context Protocol over stdio, so a coding agent can apply your spec whenever it makes images:

```json
{"mcpServers": {"picspec": {"command": "picspec", "args": ["mcp"]}}}
```

It offers `picspec_rules`, `picspec_compile` (the prompt with your spec applied, for any image tool the agent has), `picspec_generate`, `picspec_check`, `picspec_learn` and `picspec_library`. Keys and models come from the same environment variables as the command line.

**ComfyUI nodes.** Copy the [comfyui](comfyui) folder to `ComfyUI/custom_nodes/picspec` and install `picspec` in ComfyUI's Python. *PicSpec Prompt* turns a short prompt and a spec path into positive and negative text for your CLIP Text Encode nodes. *PicSpec Check* takes a finished image and returns the rule report and a pass flag.

## Measuring what your spec changes

One before/after pair proves little. `picspec bench` runs a list of prompts twice, bare and with the spec, checks every image against every rule, and prints how often each rule is met:

```bash
picspec bench examples/prompts.txt --quality medium -o bench1            # 2 image requests per prompt
picspec bench examples/prompts.txt --quality medium --rounds 2 -o bench2  # also the result after repair
```

Results are saved after every prompt, and running the same command again continues an interrupted run. `bench.md` holds the table and the folder keeps every image.

A live run with repair, six prompts, starter spec, medium quality:

| | Bare prompt | With spec | After repair |
| --- | --- | --- | --- |
| All rules | 12/41 (29%) | 27/42 (64%) | 37/42 (88%) |
| Images meeting every must rule | 0/6 | 0/6 | 6/6 |

All six repairs were done in code (a crop, added grain or both), so the repair column cost no image request: 12 requests for the whole run. Two cautions. Grain and framing were decided by measurement here, with thresholds stricter than the judge, which is why "with spec" looks lower than in the ten-prompt table above. And the repair column is scored by the same measurements that drove the repair: it shows the repairs hit their targets. A person looking at the results agreed with two of three and found the third cropped tighter than it needed to be, which is what led to the looser framing default.

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
| `measure` | Let a tool decide the rule instead of the judge. Today: `face-match`, optionally `face-match >= 0.5` | None |
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
2. **Check and repair.** Done, including measured rules and repairs in code.
3. **Learn from feedback.** Done: `picspec learn`.
4. **More ways to use it.** Done: MCP server and ComfyUI nodes. Still open: reference images for local models, and a live run of the ComfyUI adapter and nodes.
5. **Benchmark.** The tool is done (`picspec bench`). Still open: runs at scale across models and rule categories, and a judge that can be trusted on skin and expression.

## License

Apache-2.0
