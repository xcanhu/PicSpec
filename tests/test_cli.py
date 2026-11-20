import json

import pytest
from PIL import Image

from picspec.cli import main


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in ("OPENAI_API_KEY", "PICSPEC_OPENAI_API_KEY", "OPENAI_BASE_URL", "PICSPEC_OPENAI_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    assert main(["init", "--lang", "zh"]) == 0
    return tmp_path


def test_init_refuses_to_overwrite(project, capsys):
    assert main(["init"]) == 2
    assert "already exists" in capsys.readouterr().err
    assert main(["init", "--force", "--lang", "en"]) == 0
    assert "## Image look" in (project / "PICSPEC.md").read_text(encoding="utf-8")


def test_lint_lists_rules_and_fails_on_errors(project, capsys):
    assert main(["lint"]) == 0
    out = capsys.readouterr().out
    assert "7 rules" in out and "f1" in out and "-> no" in out
    (project / "PICSPEC.md").write_text("- a\n  - bogus: 1\n", encoding="utf-8")
    assert main(["lint"]) == 1
    assert "error: line 2" in capsys.readouterr().out
    assert main(["compile", "x", "--backend", "mock"]) == 2
    assert "has errors" in capsys.readouterr().err


def test_fmt_fills_in_ids(project, capsys):
    path = project / "PICSPEC.md"
    path.write_text("## Avoid\n- Watermarks\n", encoding="utf-8")
    assert main(["fmt", "--check"]) == 1
    assert main(["fmt"]) == 0
    assert "- `f1` Watermarks" in path.read_text(encoding="utf-8")
    assert main(["fmt", "--check"]) == 0


def test_compile_shows_what_is_sent_without_a_key(project, capsys):
    assert main(["compile", "雨后的小巷", "--skip", "t3", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["backend"] == "gpt-image-2"
    assert data["prompt"].startswith("雨后的小巷\n\n整体风格：") and "侧逆光" not in data["prompt"]
    assert main(["compile", "x", "--skip", "nope"]) == 2
    assert "no such rule: nope" in capsys.readouterr().err


def test_generate_writes_images_and_a_record(project, capsys):
    assert main(["generate", "雨后的小巷", "--backend", "mock", "-n", "2", "--baseline",
                 "--seed", "3", "--size", "64x96", "-o", "out"]) == 0
    record = json.loads((project / "out" / "run.json").read_text(encoding="utf-8"))
    assert [i["file"] for i in record["images"]] == ["baseline.png", "image-1.png", "image-2.png"]
    assert [i["seed"] for i in record["images"]] == [3, 3, 4]
    assert record["images"][0]["prompt_sent"] == "雨后的小巷"
    assert "画面质感" in record["images"][1]["prompt_sent"]
    assert len(record["rules"]) == 7 and record["rules"][-1]["expect"] == "no"
    assert Image.open(project / "out" / "image-1.png").size == (64, 96)


def test_generate_without_a_key_explains(project, capsys):
    assert main(["generate", "x", "-o", "out"]) == 2
    assert "OPENAI_API_KEY" in capsys.readouterr().err
    assert json.loads((project / "out" / "run.json").read_text(encoding="utf-8"))["images"] == []


def test_no_spec_is_explained(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["lint"]) == 2
    assert "picspec init" in capsys.readouterr().err
