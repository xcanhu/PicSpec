from importlib import resources

import pytest
from PIL import Image

from picspec import SpecError, dumps, find, load, loads

BASIC = """\
# Portraits

Film look, natural light.

## Image look
- Fine grain
  - check: Is grain visible?
- `sharp` Sharp face,
  eyes in focus
  - when: a person is visible
  - level: should

## Subject and composition
- Subject faces left

## Avoid
- `f9` Plastic skin
  - check: Is the skin plastic?
  - expect: no
  - negative: plastic skin, airbrushed
- Watermarks
"""


def test_parses_rules_kinds_and_fields():
    spec = loads(BASIC)
    assert spec.name == "Portraits" and spec.lang == "en"
    assert spec.summary == "Film look, natural light."
    assert [c.kind for c in spec.categories] == ["texture", "composition", "forbid"]
    assert [r.id for r in spec.rules] == ["t1", "sharp", "c1", "f9", "f1"]
    sharp = spec.rule("sharp")
    assert sharp.text == "Sharp face, eyes in focus"
    assert sharp.when == "a person is visible" and sharp.level == "should"
    f9 = spec.rule("f9")
    assert f9.kind == "forbid" and f9.expect is False and f9.negative == "plastic skin, airbrushed"
    assert not spec.errors


def test_question_falls_back_to_the_rule_text():
    spec = loads(BASIC)
    assert spec.rule("t1").question() == "Is grain visible?"
    left = spec.rule("c1")
    assert left.text in left.question() and left.expected_answer is True
    assert any("c1 has no" in p.message for p in spec.problems)


def test_chinese_fields_and_fullwidth_colon():
    spec = loads("""\
## 禁忌
- 塑料感皮肤
  - 核对：皮肤是否有塑料感？
  - 期望：否
  - 级别：尽量
  - 参考图：refs/a.png | 不要这种
""")
    r = spec.rules[0]
    assert spec.lang == "zh" and r.kind == "forbid" and r.id == "f1"
    assert r.check == "皮肤是否有塑料感？" and r.expect is False and r.level == "should"
    assert (r.refs[0].path, r.refs[0].note) == ("refs/a.png", "不要这种")
    assert "核对：" in dumps(spec) and "期望：否" in dumps(spec)


def test_front_matter_settings():
    spec = loads("---\npicspec: 1\nlang: en\nsize: 1024x1536\nquality: high\nfoo: bar\n---\n- 规则\n")
    assert spec.lang == "en" and spec.settings == {"size": "1024x1536", "quality": "high"}
    assert any('"foo"' in p.message and p.level == "warning" for p in spec.problems)
    assert loads("---\npicspec: 2\n---\n- a\n").errors
    assert loads("---\nsize: big\n---\n- a\n").errors


def test_reports_errors_with_line_numbers():
    spec = loads("## Look\n- `a` one\n  - chek: typo\n  - expect: maybe\n- `a` two\n-\n")
    messages = {p.line: p.message for p in spec.errors}
    assert "not a rule field" in messages[3]
    assert "yes or no" in messages[4]
    assert "already used on line 2" in messages[5]


def test_forbid_rule_expecting_yes_is_flagged():
    spec = loads("## Avoid\n- Watermarks\n  - check: Is there a watermark?\n")
    assert any('expect: no' in p.message for p in spec.problems) and not spec.errors


def test_code_fences_and_comments_are_not_rules():
    spec = loads("# T\n\n<!--\n- not a rule\n-->\n\n## Look\n\n```\n- also not a rule\n```\n\n- real\n")
    assert [r.text for r in spec.rules] == ["real"]
    assert spec.summary == ""


def test_kind_can_be_overridden_per_rule():
    spec = loads("## Misc\n- No logos\n  - kind: forbid\n")
    assert spec.rules[0].kind == "forbid" and spec.rules[0].id == "f1"
    assert "kind: forbid" in dumps(spec)


def test_dumps_round_trips():
    spec = loads(BASIC)
    text = dumps(spec)
    again = loads(text)
    assert dumps(again) == text
    assert [(r.id, r.text, r.kind, r.check, r.expect, r.level, r.when, r.negative) for r in again.rules] == \
           [(r.id, r.text, r.kind, r.check, r.expect, r.level, r.when, r.negative) for r in spec.rules]
    assert "- `t1` Fine grain" in text


@pytest.mark.parametrize("lang", ["zh", "en"])
def test_templates_are_valid_and_canonical(lang):
    text = resources.files("picspec").joinpath("templates").joinpath(f"{lang}.md").read_text(encoding="utf-8")
    spec = loads(text)
    assert not spec.problems
    assert spec.lang == lang and len(spec.rules) == 7
    assert dumps(spec) == text


def test_load_find_and_missing_reference(tmp_path):
    (tmp_path / "refs").mkdir()
    Image.new("RGB", (8, 8)).save(tmp_path / "refs" / "ok.png")
    path = tmp_path / "PICSPEC.md"
    path.write_text("- grain\n  - check: grain?\n  - ref: refs/ok.png\n  - ref: refs/gone.png\n", encoding="utf-8")
    spec = load(path)
    assert [p.message for p in spec.problems] == ["rule r1: reference image refs/gone.png was not found"]
    assert spec.ref_path(spec.rules[0].refs[0]) == tmp_path / "refs" / "ok.png"
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    assert find(deep) == path

    path.write_text("- x\n  - nope\n", encoding="utf-8")
    with pytest.raises(SpecError, match="not a rule field"):
        load(path)
    assert load(path, strict=False).errors
