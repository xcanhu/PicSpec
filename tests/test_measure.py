from PIL import Image

from picspec import loads
from picspec.backends import make_backend
from picspec.face import Face
from picspec.judge import FAIL, NOT_APPLICABLE, PASS, check_image
from picspec.loop import generate_checked
from picspec.measure import add_grain, crop_to_face_share, fix, grain_level

SPEC = """\
## Image look
- `grain` Film grain
  - check: Is grain visible?
  - measure: grain >= 3

## Subject and composition
- `waist` Waist-up framing
  - check: Is this framed from the waist up?
  - when: a person is in the image
  - measure: face-share 0.18..0.32
- `left` Faces left
  - check: Does the person face left?
"""
FLAT = Image.new("RGB", (400, 600), (120, 110, 100))


class Faces:
    """A fake detector: one face whose height is a fixed share of whatever image it is shown,
    unless that image has been cropped and enlarged (then the share grows with it)."""

    def __init__(self, box=(180, 100, 40, 60)):
        self.box = box

    def detect(self, image):
        return [Face(self.box, 0.9)] if self.box else []


class Judge:
    model = "fake"

    def __init__(self):
        self.asked = []

    def chat(self, system, user, images=None):
        import json
        questions = json.JSONDecoder().raw_decode(user.split("Questions:\n", 1)[1])[0]
        self.asked.append([q["id"] for q in questions])
        return json.dumps({"answers": [{"id": q["id"], "seen": "x", "answer": "yes"} for q in questions]})


def test_grain_level_follows_the_noise_added():
    assert grain_level(FLAT) < 0.5
    levels = [grain_level(add_grain(FLAT, s)) for s in (3, 6, 12)]
    assert levels == sorted(levels) and 2 < levels[0] < 4 and 9 < levels[2] < 14


def test_measured_rules_are_decided_without_the_judge():
    spec = loads(SPEC)
    assert spec.rule("waist").measurement == ("face-share", 0.18, 0.32)
    assert spec.rule("grain").measurement == ("grain", 3.0, None)
    judge = Judge()
    report = check_image(FLAT, spec, judge, faces=Faces())  # face is 10% of the height, no grain
    assert [(v.rule_id, v.status, v.by) for v in report.verdicts] == [
        ("grain", FAIL, "grain"), ("waist", FAIL, "face-share"), ("left", PASS, "judge")]
    assert judge.asked == [["left"]] and "10%" in report.verdicts[1].seen
    assert check_image(add_grain(FLAT, 6), spec, Judge(), faces=Faces((150, 80, 100, 150))).ok
    no_face = check_image(FLAT, spec, Judge(), faces=Faces(None))
    assert no_face.verdicts[1].status == NOT_APPLICABLE
    judge = Judge()  # without face tools the framing rule goes back to the judge; grain needs no tools
    report = check_image(FLAT, spec, judge, faces=None)
    assert judge.asked == [["waist", "left"]] and report.verdicts[0].by == "grain"


def test_crop_brings_the_face_to_the_target_share():
    image = Image.new("RGB", (400, 600), "white")
    image.paste((200, 0, 0), (180, 100, 220, 160))  # the "face": 40x60, 10% of the height
    out = crop_to_face_share(image, Face((180, 100, 40, 60), 0.9), 0.2)
    assert out.size == image.size
    red = out.convert("RGB").point(lambda v: 255 if v > 128 else 0).getchannel("G").point(lambda v: 255 - v).getbbox()
    assert abs((red[3] - red[1]) / out.height - 0.2) < 0.01 and red[0] > 0 and red[2] < out.width
    assert crop_to_face_share(image, Face((180, 100, 40, 60), 0.9), 0.5) is None   # would enlarge 5x
    assert crop_to_face_share(image, Face((180, 100, 40, 200), 0.9), 0.2) is None  # already larger


def test_fix_crops_then_restores_grain():
    spec = loads(SPEC)
    fixed, done = fix(FLAT, spec, ["grain", "waist"], Faces((180, 100, 48, 72)))
    assert done == ["waist", "grain"] and grain_level(fixed) >= 3 and fixed.size == FLAT.size
    assert fix(FLAT, spec, ["left"], Faces()) == (FLAT, [])
    assert fix(FLAT, spec, ["waist"], None)[1] == []  # no face tools: nothing to crop with


def test_loop_fixes_in_code_before_spending_on_another_image():
    spec = loads(SPEC.replace("  - measure: face-share 0.18..0.32\n", ""))  # grain is the only measured rule
    seen = []
    outcome = generate_checked(spec, "a street", make_backend("mock"), Judge(), rounds=3, faces=None,
                               size=(64, 96), on_attempt=lambda a: seen.append(a.method))
    assert seen == ["generate", "fix"] and outcome.ok and outcome.best.method == "fix"
    assert outcome.best.source == 0 and outcome.best.result.meta == {"fixed": ["grain"]}
    off = generate_checked(spec, "a street", make_backend("mock"), Judge(), rounds=1, faces=None,
                           size=(64, 96), local_fix=False)
    assert [a.method for a in off.attempts] == ["generate"] and not off.ok
