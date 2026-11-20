import json

from picspec import learn, loads
from picspec.cli import main
from picspec.spec import dumps

SPEC = """\
---
lang: zh
---

# 规格

## 画面质感

- `t1` 轻微的胶片颗粒
  - 核对：是否能看到颗粒？
"""


class Model:
    model = "fake"

    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def chat(self, system, user, images=None):
        self.calls.append((user, images))
        return self.reply if isinstance(self.reply, str) else json.dumps(self.reply, ensure_ascii=False)


REPLY = {"note": "", "changes": [
    {"action": "modify", "id": "t1", "rule": {"text": "明显的胶片颗粒", "level": "should"}, "why": "颗粒不够"},
    {"action": "add", "library": "plastic-skin", "why": "皮肤太光滑"},
    {"action": "add", "id": "warm", "rule": {"text": "整体偏暖色调", "check": "画面是否偏暖色？", "expect": "yes",
                                               "kind": "texture"}, "why": "想要暖色"},
    {"action": "add", "id": "nolens", "rule": {"text": "镜头光晕", "check": "是否有镜头光晕？", "expect": "no",
                                                 "kind": "forbid"}, "why": "不要光晕"},
    {"action": "modify", "id": "zz", "rule": {"text": "x"}},
    {"action": "add", "library": "nope"},
    {"action": "explode"},
]}


def test_propose_validates_and_apply_edits_a_copy():
    spec = loads(SPEC)
    model = Model(REPLY)
    proposal = learn.propose(spec, "皮肤太光滑，颗粒不够", model)
    assert [c.action for c in proposal.changes] == ["modify", "add", "add", "add"] and len(proposal.skipped) == 3
    user = model.calls[0][0]
    assert "Spec language: Chinese" in user and "- plastic-skin [forbid]: 过度磨皮" in user and "`t1`" in user
    after = learn.apply(spec, proposal.changes)
    assert spec.rule("t1").text == "轻微的胶片颗粒"  # the original is untouched
    assert after.rule("t1").text == "明显的胶片颗粒" and after.rule("t1").level == "should"
    assert [c.title for c in after.categories] == ["画面质感", "禁忌"]
    assert [r.id for r in after.categories[0].rules] == ["t1", "warm"]
    assert [(r.id, r.expect) for r in after.categories[1].rules] == [("plastic-skin", False), ("nolens", False)]
    again = loads(dumps(after))  # what is written parses back to the same rules
    assert not again.errors and [(r.id, r.kind) for r in again.rules] == [(r.id, r.kind) for r in after.rules]
    assert "+- `warm` 整体偏暖色调" in learn.diff(spec, after) and learn.diff(spec, spec) == ""
    removed = learn.apply(after, [learn.Change("remove", "nolens"), learn.Change("remove", "plastic-skin")])
    assert [c.title for c in removed.categories] == ["画面质感"]


def test_learn_command_shows_a_diff_and_writes_only_with_apply(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "PICSPEC.md").write_text(SPEC, encoding="utf-8")
    monkeypatch.setattr("picspec.cli.make_judge", lambda *a, **k: Model(REPLY))
    assert main(["learn", "皮肤太光滑"]) == 0
    out = capsys.readouterr()
    assert "add    plastic-skin: 皮肤太光滑" in out.out and "+- `plastic-skin`" in out.out and "--apply" in out.out
    assert (tmp_path / ".picspec-learn.json").is_file()
    assert "skipped: unknown library rule" in out.err
    assert (tmp_path / "PICSPEC.md").read_text(encoding="utf-8") == SPEC
    # --apply writes the previewed proposal without asking the model again
    monkeypatch.setattr("picspec.cli.make_judge", lambda *a, **k: Model({"changes": [], "note": "changed its mind"}))
    assert main(["learn", "--apply"]) == 0
    assert "`plastic-skin`" in (tmp_path / "PICSPEC.md").read_text(encoding="utf-8")
    assert not (tmp_path / ".picspec-learn.json").exists() and "已写入" in capsys.readouterr().out
    assert main(["learn", "--apply"]) == 2  # nothing saved any more and no feedback given
    assert main(["lint"]) == 0
    monkeypatch.setattr("picspec.cli.make_judge", lambda *a, **k: Model({"changes": [], "note": "只和这一张图有关"}))
    capsys.readouterr()
    assert main(["learn", "这张让她笑一下"]) == 0
    assert "没有需要对规格做的改动。" in capsys.readouterr().out
    monkeypatch.setattr("picspec.cli.make_judge", lambda *a, **k: Model("not json"))
    assert main(["learn", "x"]) == 2
