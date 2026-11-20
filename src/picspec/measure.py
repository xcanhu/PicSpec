"""Rules decided by measurement instead of by asking a vision model, and repairs done in code.

A rule opts in with a ``measure`` field. Each measure returns one number; the rule passes when the
number lies inside its allowed range. Two of them can also be repaired without calling an image
model: a face that is too small in the frame is fixed by cropping, and missing grain is added.
"""

from __future__ import annotations

from typing import Any

from PIL import Image, ImageChops, ImageFilter, ImageStat

from .spec import Rule, Spec

# A crop is enlarged back to the original size. Past this factor the result looks soft.
MAX_ENLARGE = 2.0
_GRAIN_STEPS = (2.0, 3.0, 4.0, 6.0, 8.0, 11.0, 15.0, 20.0)


def grain_level(image: Image.Image, block: int = 48) -> float:
    """Fine noise in the flat areas of an image, on a 0-255 scale.

    The image minus a blurred copy leaves grain and edges. Edges are local, so the level is taken
    from the quieter blocks: the lower quartile of the per-block standard deviation.
    """
    gray = image.convert("L")
    residual = ImageChops.subtract(gray, gray.filter(ImageFilter.GaussianBlur(1.5)), 1, 128)
    step = max(block, max(gray.size) // 40)  # at most about 40 blocks a side
    values = []
    for top in range(0, gray.height - block + 1, step):
        for left in range(0, gray.width - block + 1, step):
            values.append(ImageStat.Stat(residual.crop((left, top, left + block, top + block))).stddev[0])
    if not values:
        return ImageStat.Stat(residual).stddev[0]
    values.sort()
    return values[len(values) // 4]


def add_grain(image: Image.Image, sigma: float) -> Image.Image:
    """Add zero-mean luminance noise with the given standard deviation (0-255 scale)."""
    noise = Image.effect_noise(image.size, sigma).convert("RGB")
    return ImageChops.add(image.convert("RGB"), noise, 1, -128)


def face_share(image: Image.Image, faces: Any) -> float | None:
    """Height of the largest face as a share of the image height, or ``None`` without a face."""
    found = faces.detect(image)
    return found[0].box[3] / image.height if found else None


def _inside(value: float, low: float | None, high: float | None) -> bool:
    return (low is None or value >= low) and (high is None or value <= high)


def _range(low: float | None, high: float | None) -> str:
    if low is not None and high is not None:
        return f"{low:g}..{high:g}"
    return f">= {low:g}" if low is not None else f"<= {high:g}"


def _face_match(image: Image.Image, rule: Rule, spec: Spec, faces: Any) -> tuple[float, str] | str | None:
    """(best similarity, reference path), a reason why nothing can be compared, or ``None`` to ask the judge."""
    found = faces.detect(image)
    if not found:
        return "no-face"
    if all(getattr(f, "profile", False) for f in found):
        return "turned"
    best: tuple[float, str] | None = None  # several references (front, three-quarter view...): the closest counts
    for ref in rule.refs:
        try:
            score = faces.similarity(image, Image.open(spec.ref_path(ref)).convert("RGB"))
        except Exception:
            continue
        if score is not None and (best is None or score > best[0]):
            best = (score, ref.path)
    return best


_WORDS = {
    "en": {"no-face": "no face was found to measure", "turned": "the face is turned too far to compare",
           "face-match": "face similarity {v:.2f} against {ref}; allowed {r}",
           "face-share": "the face is {v:.0%} of the image height; allowed {r}",
           "grain": "grain level {v:.1f}; allowed {r}"},
    "zh": {"no-face": "没有找到可测量的人脸", "turned": "脸转得太偏，无法比对",
           "face-match": "与 {ref} 的人脸相似度为 {v:.2f}；允许范围 {r}",
           "face-share": "脸占图高的 {v:.0%}；允许范围 {r}",
           "grain": "颗粒强度 {v:.1f}；允许范围 {r}"},
}


def evaluate(image: Image.Image, rule: Rule, spec: Spec, faces: Any) -> tuple[str, str, str] | None:
    """Decide ``rule`` by measurement. Returns (answer, what was seen, measure name), or ``None`` when the
    rule has no measure or its tool is missing, which leaves the rule to the judge."""
    wanted = rule.measurement
    if wanted is None:
        return None
    name, low, high = wanted
    words = _WORDS["zh" if spec.lang == "zh" else "en"]
    ref = ""
    try:
        if name == "grain":
            value: float | None = grain_level(image)
        elif faces is None:
            return None
        elif name == "face-share":
            value = face_share(image, faces)
            if value is None:
                return ("na" if rule.when else ("no" if rule.expect else "yes")), words["no-face"], name
        else:
            got = _face_match(image, rule, spec, faces)
            if got is None:
                return None
            if isinstance(got, str):
                return ("na" if rule.when else ("no" if rule.expect else "yes")), words[got], name
            value, ref = got
    except Exception:  # a tool failure must not stop the check
        return None
    ok = _inside(value, low, high)
    return ("yes" if ok == rule.expect else "no"), words[name].format(v=value, ref=ref, r=_range(low, high)), name


def crop_to_face_share(image: Image.Image, face: Any, target: float) -> Image.Image | None:
    """Crop around ``face`` so that it takes ``target`` of the height, then enlarge back to the original
    size. ``None`` when the face is already that large or the enlargement would be too strong."""
    x, y, w, h = face.box
    share = h / image.height
    if share >= target or target / share > MAX_ENLARGE:
        return None
    new_h = round(h / target)
    new_w = round(new_h * image.width / image.height)
    left = min(max(0, x + w // 2 - new_w // 2), image.width - new_w)
    top = min(max(0, y + h // 2 - round(new_h * 0.36)), image.height - new_h)  # face a little above the middle
    return image.crop((left, top, left + new_w, top + new_h)).resize(image.size, Image.LANCZOS)


def fix(image: Image.Image, spec: Spec, failed: list[str], faces: Any) -> tuple[Image.Image, list[str]]:
    """Repair what can be repaired in code among the ``failed`` rules.

    Returns the new image and the ids of the rules that were worked on (empty when nothing applied).
    Cropping runs before grain, because enlarging a crop softens grain.
    """
    done: list[str] = []
    rules = [spec.rule(i) for i in failed if spec.rule(i).measurement]
    for r in rules:
        name, low, high = r.measurement
        if name != "face-share" or faces is None or low is None or not r.expect:
            continue
        try:
            found = faces.detect(image)
        except Exception:
            continue
        if not found:
            continue
        target = min(low * 1.12, high) if high is not None else low * 1.12
        cropped = crop_to_face_share(image, found[0], target)
        if cropped is not None:
            image, done = cropped, done + [r.id]
    grain_rules = [r for r in spec.rules if r.measurement and r.measurement[0] == "grain" and r.expect
                   and r.measurement[1] is not None and (r.id in failed or done)]
    for r in grain_rules:  # also after a crop, which may have softened grain that was there
        low = r.measurement[1]
        if grain_level(image) >= low:
            continue
        for sigma in _GRAIN_STEPS:
            candidate = add_grain(image, sigma)
            if grain_level(candidate) >= low * 1.1:
                image, done = candidate, done + [r.id]
                break
    return image, done
