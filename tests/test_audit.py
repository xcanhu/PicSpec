import json

import pytest
from PIL import Image, ImageStat

from picspec import loads
from picspec.audit import PROBES, add_grain, add_text, audit_judge, blur, parse_probe
from picspec.cli import main

SPEC = """\
## Look
- `t1` Fine grain
  - check: Is grain visible?
- `t2` Sharp face
  - check: Is the face sharp?
## Subject
- `c1` Faces left
  - check: Does the person face left?
## Avoid
- `f2` Text
  - check: Is there text?
  - expect: no
"""


def test_changes_do_what_they_say():
    flat = Image.new("RGB", (256, 384), (120, 120, 120))
    assert ImageStat.Stat(add_grain(flat, 25)).stddev[0] > 15 > ImageStat.Stat(add_grain(flat, 4)).stddev[0] > 2
    assert abs(ImageStat.Stat(add_grain(flat, 25)).mean[0] - 120) < 3  # noise does not shift brightness
    assert add_text(flat).getextrema() != flat.getextrema() and add_text(flat).size == flat.size
    half = Image.new("RGB", (256, 256), "black")
    half.paste("white", (128, 0, 256, 256))
    assert 0 < blur(half, 4).getpixel((126, 100))[0] < 255
    assert PROBES["flip"].apply(half, 1).getpixel((10, 10)) == (255, 255, 255)


def test_parse_probe():
    spec = loads(SPEC)
    assert parse_probe("blur=t2", spec)[1:] == ("t2", "no")
    assert parse_probe("smooth=t1:no", spec)[2] == "no" and parse_probe("flip=c1", spec)[2] == "invert"
    for bad in ("sharpen=t1", "blur", "flip=c1:yes", "blur=t2:invert"):
        with pytest.raises(ValueError):
            parse_probe(bad, spec)
    with pytest.raises(KeyError):
        parse_probe("blur=zz", spec)


class Oracle:
    """A judge that knows what was done to the image from its pixels, with switches to make it wrong."""

    model = "oracle"

    def __init__(self, blind_to=(), flips_grain_on_mirror=False):
        self.blind_to, self.flips_grain_on_mirror, self.calls = set(blind_to), flips_grain_on_mirror, 0

    def chat(self, system, user, images=None):
        self.calls += 1
        im = images[0]
        noisy = ImageStat.Stat(im.crop((108, 200, 148, 240))).stddev[0] > 8
        mirrored = im.getpixel((im.width - 5, 5))[0] > 200  # the marker starts in the top-left corner
        soft = ImageStat.Stat(im.crop((108, 60, 148, 100))).stddev[0] < 60  # a checker pattern lives here
        has_text = ImageStat.Stat(im.crop((0, int(im.height * 0.8), im.width, im.height))).stddev[0] > 30
        truth = {"t1": noisy, "t2": not soft, "c1": not mirrored, "f2": has_text}
        if self.flips_grain_on_mirror and mirrored:
            truth["t1"] = not truth["t1"]
        for rid in self.blind_to:
            truth[rid] = {"t1": False, "t2": True, "c1": True, "f2": False}[rid]
        ids = [q["id"] for q in json.loads(user.split("Questions:\n", 1)[1])]
        return json.dumps({"answers": [{"id": i, "seen": "x", "answer": "yes" if truth[i] else "no"} for i in ids]})


def picture():
    im = Image.new("RGB", (256, 384), (90, 90, 90))
    im.paste((255, 255, 255), (0, 0, 10, 10))  # marker: top-left
    for x in range(108, 148, 4):
        for y in range(60, 100, 4):
            im.paste((255, 255, 255) if (x + y) // 4 % 2 else (0, 0, 0), (x, y, x + 4, y + 4))
    return im


ALL = ["flip=c1", "text=f2", "grain=t1", "blur=t2"]


def run(judge, **kw):
    spec = loads(SPEC)
    return audit_judge({"a": picture()}, spec, judge, [parse_probe(p, spec) for p in ALL], **kw)


def test_a_judge_that_sees_everything_scores_full_marks():
    judge = Oracle()
    audit = run(judge)
    assert [(r["probe"], r["correct"], r["trials"]) for r in audit.summary()] == [
        ("flip", 1, 1), ("text", 1, 1), ("grain", 1, 1), ("blur", 1, 1)]
    grain = next(r for r in audit.summary() if r["probe"] == "grain")
    assert grain["yes_by_level"] == {4: "0/1", 10: "1/1", 25: "1/1"}
    assert audit.stability() == {"repeat": (4, 4), "flip": (3, 3)}
    assert judge.calls == 2 + 1 + 1 + 3 + 3


def test_a_blind_judge_is_caught():
    audit = run(Oracle(blind_to={"f2", "c1", "t2"}), repeat=False)
    got = {r["probe"]: (r["correct"], r["trials"]) for r in audit.summary()}
    assert got == {"flip": (0, 1), "text": (0, 1), "grain": (1, 1), "blur": (0, 1)}
    assert "repeat" not in audit.stability()


def test_an_answer_that_moves_when_it_should_not_is_caught():
    assert run(Oracle(flips_grain_on_mirror=True)).stability()["flip"] == (2, 3)


def test_flip_only_counts_images_where_the_answer_was_yes():
    spec = loads(SPEC)
    mirrored = PROBES["flip"].apply(picture(), 1)  # the person now "faces right": nothing must flip
    audit = audit_judge({"a": mirrored}, spec, Oracle(), [parse_probe("flip=c1", spec)], repeat=False)
    assert audit.summary()[0]["trials"] == 0 and audit.trials[0].correct is None


def test_cli_audit(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "PICSPEC.md").write_text(SPEC, encoding="utf-8")
    picture().save(tmp_path / "a.png")
    monkeypatch.setattr("picspec.cli.make_judge", lambda *a: Oracle(blind_to={"f2"}))
    assert main(["audit", "a.png"]) == 2 and "PROBE=RULE" in capsys.readouterr().err
    assert main(["audit", "a.png", "--probe", "sharpen=t1"]) == 2
    args = ["audit", "a.png", "-o", "out"] + [x for p in ALL for x in ("--probe", p)]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "text    f2    0/1 correct" in out and "grain   t1    1/1 correct" in out
    assert "yes at each level: 4: 0/1, 10: 1/1, 25: 1/1" in out and "stable  4/4 answers unchanged" in out
    data = json.loads((tmp_path / "out" / "audit.json").read_text(encoding="utf-8"))
    assert data["judge"] == "oracle" and len(data["trials"]) == 8
    assert (tmp_path / "out" / "a.grain-25.png").is_file() and (tmp_path / "out" / "a.flip-1.png").is_file()
