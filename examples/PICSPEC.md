---
picspec: 1
lang: en
size: 1024x1536
quality: high
---

# My image spec

Natural-light documentary portraits with the look of 35mm film.

<!-- The paragraph above is the overall style, sent with every prompt. Below, each top-level bullet is one rule and the indented bullets are its fields. -->
<!-- To attach a reference image to a rule, add a line under it: "  - ref: refs/grain.jpg | grain strength like this". Paths are relative to this file. -->

## Image look

- `t1` Fine film grain across the whole frame, no digital smoothness
  - check: Is an even, fine grain visible across the image?
- `t2` The face is sharp and the eyes are in focus
  - check: Are the person's eyes and face sharp, with no blur?
  - when: there is a person in the image
- `t3` Soft light from behind and to the side, with detail kept in the shadows
  - check: Does the main light come from behind and to the side of the subject, with no crushed blacks?
  - level: should

## Subject and composition

- `c1` The person faces or walks toward the left of the frame, with space ahead of them
  - check: Does the person face or move toward the left of the frame?
  - when: there is a person in the image
- `c2` Medium shot, from the waist up
  - check: Is this a medium shot showing the person from the waist up?
  - when: there is a person in the image

## Avoid

<!-- Rules in this section name the unwanted thing itself. The check asks whether it is present, so expect is "no". -->

- `f1` Over-smoothed, plastic-looking skin
  - check: Does the skin look over-smoothed or plastic?
  - expect: no
- `f2` Text, watermarks or logos
  - check: Does the image contain any text, watermark or logo?
  - expect: no
