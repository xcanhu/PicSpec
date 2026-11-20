import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from PIL import Image

from picspec import loads
from picspec.backends import make_backend
from picspec.cli import main
from picspec.judge import FAIL, NOT_APPLICABLE, PASS, UNKNOWN, check_image
from picspec.llm import OpenAIChat, extract_json, make_judge
from picspec.loop import generate_checked

SPEC = """\
## Image look
- `t1` Fine grain
  - check: Is grain visible?
- `t2` Sharp face
  - check: Is the face sharp?
  - when: a person is visible
- `t3` Backlight
  - check: Is the subject backlit?
  - level: should

## Avoid
- `f1` Watermarks
  - check: Is there a watermark?
  - expect: no
"""


class FakeJudge:
    """Answers from a script: each entry maps rule id to an answer, or is a raw reply string."""

    model = "fake-judge"

    def __init__(self, *script):
        self.script, self.calls = list(script), []

    def chat(self, system, user, images=None):
        questions = json.loads(user.split("Questions:\n", 1)[1].split("\n\nTwo images")[0])
        self.calls.append({"questions": questions, "images": images, "user": user})
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, str):
            return step
        return json.dumps({"answers": [{"id": q["id"], "seen": f"saw {q['id']}", "answer": step[q["id"]]}
                                       for q in questions if q["id"] in step]})


ALL_GOOD = {"t1": "yes", "t2": "yes", "t3": "yes", "f1": "no"}
IMG = Image.new("RGB", (64, 64))


def test_verdicts_follow_the_expected_answer():
    judge = FakeJudge({"t1": "no", "t2": "na", "t3": "No", "f1": "yes"})
    report = check_image(IMG, loads(SPEC), judge)
    assert [v.status for v in report.verdicts] == [FAIL, NOT_APPLICABLE, FAIL, FAIL]
    assert report.failed == ["t1", "f1", "t3"]  # must-level first
    assert report.must_failed == ["t1", "f1"] and not report.ok
    assert report.counts == (0, 3) and report.verdicts[0].seen == "saw t1"
    asked = judge.calls[0]["questions"]
    assert asked[1] == {"id": "t2", "question": "Is the face sharp?", "condition": "a person is visible"}
    assert "condition" not in asked[0]


def test_should_level_failures_do_not_fail_the_image():
    report = check_image(IMG, loads(SPEC), FakeJudge({**ALL_GOOD, "t3": "no"}))
    assert report.ok and report.failed == ["t3"] and report.counts == (3, 4)


def test_na_without_a_condition_and_garbage_are_unknown():
    report = check_image(IMG, loads(SPEC), FakeJudge({"t1": "na", "t2": "maybe", "t3": "yes", "f1": "no"}))
    assert [v.status for v in report.verdicts] == [UNKNOWN, UNKNOWN, PASS, PASS] and not report.ok
    report = check_image(IMG, loads(SPEC), FakeJudge("I cannot look at images."))
    assert {v.status for v in report.verdicts} == {UNKNOWN}


def test_skipped_answers_are_asked_again():
    judge = FakeJudge({"t1": "yes", "f1": "no"}, {"t2": "yes", "t3": "yes"})
    report = check_image(IMG, loads(SPEC), judge)
    assert report.ok and report.counts == (4, 4)
    assert [q["id"] for q in judge.calls[1]["questions"]] == ["t2", "t3"]


def test_one_by_one_and_only():
    judge = FakeJudge(ALL_GOOD)
    report = check_image(IMG, loads(SPEC), judge, only=["t1", "f1"], one_by_one=True)
    assert [len(c["questions"]) for c in judge.calls] == [1, 1] and report.counts == (2, 2)


def test_large_images_get_a_full_resolution_crop_for_texture_rules():
    judge = FakeJudge(ALL_GOOD)
    check_image(Image.new("RGB", (2048, 3072)), loads(SPEC), judge)
    views = judge.calls[0]["images"]
    assert [v.size for v in views] == [(2048, 3072), (768, 768)] and "Two images" in judge.calls[0]["user"]
    judge = FakeJudge(ALL_GOOD)
    check_image(Image.new("RGB", (2048, 3072)), loads(SPEC), judge, only=["f1"])
    assert len(judge.calls[0]["images"]) == 1


def test_loop_stresses_failed_rules_and_stops_when_met():
    judge = FakeJudge({**ALL_GOOD, "t1": "no", "f1": "yes"}, {**ALL_GOOD, "t1": "no"}, ALL_GOOD, ALL_GOOD)
    outcome = generate_checked(loads(SPEC), "a cat", make_backend("mock"), judge, rounds=5, seed=10)
    assert [a.round for a in outcome.attempts] == [1, 2, 3] and outcome.ok
    assert [a.stressed for a in outcome.attempts] == [[], ["t1", "f1"], ["t1"]]
    assert [a.seed for a in outcome.attempts] == [10, 11, 12]
    assert outcome.best is outcome.attempts[2]
    second = outcome.attempts[1].result.rendered.prompt
    assert second.index("Most important") < second.index("Fine grain") < second.index("Image look:")


def test_loop_gives_up_after_the_rounds_and_keeps_the_best():
    judge = FakeJudge({**ALL_GOOD, "t1": "no", "f1": "yes"}, {**ALL_GOOD, "t1": "no"}, {**ALL_GOOD, "t1": "no"})
    outcome = generate_checked(loads(SPEC), "a cat", make_backend("mock"), judge, rounds=2, candidates=2)
    assert len(outcome.attempts) == 4 and not outcome.ok
    assert outcome.best is outcome.attempts[1] and outcome.best.report.failed == ["t1"]


@pytest.fixture
def chat_api():
    state = {"bodies": [], "replies": []}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            state["bodies"].append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            code, payload = state["replies"].pop(0) if state["replies"] else (
                200, {"choices": [{"message": {"content": "```json\n{\"answers\": []}\n```"}}]})
            out = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{server.server_address[1]}/v1"
    yield state
    server.shutdown()


def test_chat_client_sends_images_and_drops_a_rejected_temperature(chat_api):
    chat_api["replies"] = [(400, {"error": {"message": "Unsupported value: 'temperature'"}})]
    chat = OpenAIChat("vision-model", base_url=chat_api["url"], api_key="k", retry_wait=0)
    assert extract_json(chat.chat("sys", "hello", images=[IMG])) == {"answers": []}
    first, second = chat_api["bodies"]
    assert first["temperature"] == 0.0 and "temperature" not in second
    content = second["messages"][1]["content"]
    assert content[0] == {"type": "text", "text": "hello"}
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_make_judge_reads_the_environment(monkeypatch):
    for name in ("PICSPEC_JUDGE_MODEL", "PICSPEC_JUDGE_BASE_URL", "PICSPEC_JUDGE_API_KEY",
                 "PICSPEC_OPENAI_BASE_URL", "PICSPEC_OPENAI_API_KEY", "OPENAI_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-main")
    with pytest.raises(ValueError, match="--judge"):
        make_judge()
    monkeypatch.setenv("PICSPEC_JUDGE_MODEL", "vl")
    monkeypatch.setenv("PICSPEC_JUDGE_BASE_URL", "http://judge/v1")
    judge = make_judge()
    assert (judge.model, judge.base_url, judge.api_key) == ("vl", "http://judge/v1", "sk-main")


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PICSPEC_JUDGE_MODEL", raising=False)
    (tmp_path / "PICSPEC.md").write_text(SPEC, encoding="utf-8")
    return tmp_path


def test_cli_generate_with_check(project, monkeypatch, capsys):
    judge = FakeJudge({**ALL_GOOD, "t1": "no"}, {**ALL_GOOD, "t1": "no"}, ALL_GOOD)
    monkeypatch.setattr("picspec.cli.make_judge", lambda *a: judge)
    assert main(["generate", "a cat", "--backend", "mock", "--check", "--baseline", "--seed", "1", "-o", "out"]) == 0
    record = json.loads((project / "out" / "run.json").read_text(encoding="utf-8"))
    assert [i["file"] for i in record["images"]] == ["baseline.png", "round1-1.png", "round2-1.png"]
    assert record["best"] == "round2-1.png" and record["judge"] == "fake-judge"
    assert [i["ok"] for i in record["images"]] == [False, False, True]
    assert record["images"][2]["stressed"] == ["t1"]
    assert record["images"][0]["checks"][0] == {"rule": "t1", "status": "fail", "seen": "saw t1"}
    assert (project / "out" / "best.png").is_file()
    out = capsys.readouterr().out
    assert "3/4 rules met, not met: t1" in out and "4/4 rules met" in out


def test_cli_generate_reports_failure_after_all_rounds(project, monkeypatch):
    monkeypatch.setattr("picspec.cli.make_judge", lambda *a: FakeJudge({**ALL_GOOD, "f1": "yes"}))
    assert main(["generate", "a cat", "--backend", "mock", "--rounds", "2", "-n", "2", "-o", "out"]) == 1
    record = json.loads((project / "out" / "run.json").read_text(encoding="utf-8"))
    assert [i["file"] for i in record["images"]] == ["round1-1.png", "round1-2.png", "round2-1.png", "round2-2.png"]
    assert record["best"] == "round1-1.png"


def test_cli_check_command(project, monkeypatch, capsys):
    IMG.save(project / "a.png")
    monkeypatch.setattr("picspec.cli.make_judge", lambda *a: FakeJudge({**ALL_GOOD, "t2": "na", "f1": "yes"}))
    assert main(["check", "a.png"]) == 1
    out = capsys.readouterr().out
    assert "a.png: 2/3 rules met, not met: f1" in out and "FAIL f1" in out and "n/a  t2" in out
    assert main(["check", "a.png", "--skip", "f1", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_cli_check_needs_a_judge(project, capsys):
    IMG.save(project / "a.png")
    assert main(["check", "a.png"]) == 2
    assert "--judge" in capsys.readouterr().err
