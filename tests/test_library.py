import pytest

from picspec import library, loads
from picspec.cli import main
from picspec.spec import dumps


def test_entries_are_complete_and_unique():
    ids = [e.id for e in library.ENTRIES]
    assert len(ids) == len(set(ids))
    for e in library.ENTRIES:
        assert e.category in library.CATEGORIES and e.status in library.STATUSES and e.kind in library.SECTIONS
        assert all(e.text) and all(e.check) and (e.kind == "forbid") == (not e.expect)
        assert bool(e.when[0]) == bool(e.when[1]) and bool(e.note[0]) == bool(e.note[1])
    assert all(library.entries(c) for c in library.CATEGORIES)
    assert {e.id for e in library.entries(status="verified")} == {"film-grain", "text", "sharp-face", "faces-left", "waist-up", "photoreal"}


@pytest.mark.parametrize("name", list(library.TEMPLATES))
@pytest.mark.parametrize("lang", ["en", "zh"])
def test_templates_are_valid_canonical_specs(name, lang):
    text = dumps(library.TEMPLATES[name].spec(lang))
    spec = loads(text)
    assert not spec.errors and dumps(spec) == text
    assert [r.id for r in spec.rules] and spec.summary and spec.settings["size"]
    for r in spec.rules:  # each rule landed in a section of its own kind
        assert r.kind == library.get(r.id).kind and not r.kind_explicit


def test_drama_shot_compares_against_references():
    spec = library.TEMPLATES["drama-shot"].spec("zh")
    assert {r.id: [x.path for x in r.refs] for r in spec.rules if r.refs} == {
        "same-style": ["refs/scene.png"], "same-light": ["refs/scene.png"], "same-face": ["refs/character.png"],
        "same-outfit": ["refs/character.png"], "same-place": ["refs/scene.png"]}


def test_rules_command_lists_and_prints(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["rules", "--category", "text"]) == 0
    out = capsys.readouterr().out
    assert "[text]" in out and "overlay-text" in out and "judge verified" in out and "[style]" not in out
    assert main(["init", "--template", "portrait", "--lang", "zh"]) == 0
    assert "# 写实人像" in (tmp_path / "PICSPEC.md").read_text(encoding="utf-8")
    capsys.readouterr()
    assert main(["rules", "--status", "weak"]) == 0  # language follows the spec in this folder
    out = capsys.readouterr().out
    assert "plastic-skin" in out and "判官不可靠" in out and "film-grain" not in out
    assert main(["rules", "bad-hands", "film-grain", "--lang", "en"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("## Image look") and "- `bad-hands`" in out and "expect: no" in out
    assert loads(out).rule("film-grain").kind == "texture"
    assert main(["rules", "nope"]) == 2
    assert "no such library rule: nope" in capsys.readouterr().err
