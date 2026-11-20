import json

from picspec import bench
from picspec.cli import main

SPEC = """\
## Image look
- `g` Film grain
  - check: Is grain visible?
  - measure: grain >= 3
- `s` Sharp face
  - check: Is the face sharp?
  - when: a person is in the image
  - level: should

## Avoid
- `w` Watermarks
  - check: Is there a watermark?
  - expect: no
"""


class Judge:
    model = "fake"

    def chat(self, system, user, images=None):
        questions = json.JSONDecoder().raw_decode(user.split("Questions:\n", 1)[1])[0]
        # the mock backend draws a flat colour: no watermark; no person in the second prompt
        answers = {"w": "no", "s": "na" if "street" in self.prompt else "no"}
        return json.dumps({"answers": [{"id": q["id"], "seen": "", "answer": answers[q["id"]]} for q in questions]})


def test_bench_compares_bare_and_spec_and_resumes(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "PICSPEC.md").write_text(SPEC, encoding="utf-8")
    (tmp_path / "prompts.txt").write_text("# comment\na woman reading\n\nan empty street\n", encoding="utf-8")
    judge = Judge()
    monkeypatch.setattr("picspec.cli.make_judge", lambda *a, **k: judge)
    import picspec.backends.mock as mock
    real = mock.MockBackend._run

    def run(self, request, rendered):
        judge.prompt = request.prompt
        return real(self, request, rendered)

    monkeypatch.setattr(mock.MockBackend, "_run", run)
    args = ["bench", "prompts.txt", "--backend", "mock", "--size", "64x96", "--rounds", "2", "-o", "out", "--json"]
    assert main(args) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["conditions"] == ["bare", "spec", "repaired"] and summary["prompts"] == 2
    assert summary["rules"]["g"] == {"bare": [0, 2], "spec": [0, 2], "repaired": [2, 2]}  # grain added in code
    assert summary["rules"]["s"]["bare"] == [0, 1]  # not applicable to the street
    assert summary["rules"]["w"]["spec"] == [2, 2]
    assert summary["images_meeting_every_must_rule"] == {"bare": [0, 2], "spec": [0, 2], "repaired": [2, 2]}
    assert summary["image_requests"] == 4  # the code fix cost no image request
    table = (tmp_path / "out" / "bench.md").read_text(encoding="utf-8")
    assert "| `g` Film grain † | 0/2 (0%) | 0/2 (0%) | 2/2 (100%) |" in table and "† Decided by a measurement" in table and "n/a" not in table.splitlines()[2]
    assert sorted(p.name for p in (tmp_path / "out").glob("*.png")) == [
        "001-bare.png", "001-repaired.png", "001-spec.png", "002-bare.png", "002-repaired.png", "002-spec.png"]

    calls = []
    monkeypatch.setattr(mock.MockBackend, "_run", lambda self, request, rendered: calls.append(1) or real(self, request, rendered))
    assert main(args) == 0 and calls == []  # everything was already done: nothing is generated again
    assert bench.read_prompts(tmp_path / "prompts.txt") == ["a woman reading", "an empty street"]


def test_a_refused_prompt_is_skipped_and_noted(tmp_path):
    from picspec import bench
    from picspec.backends.mock import MockBackend
    from picspec.spec import loads

    class Refusing(MockBackend):
        def generate(self, request):
            if "bad" in request.prompt:
                raise RuntimeError("rejected by the safety system")
            return super().generate(request)

    class Judge:
        model = "fake"

        def chat(self, system, user, images=None):
            return '{"answers": []}'

    spec = loads("---\npicspec: 1\n---\n# T\n\n## Look\n- `a` soft light\n  check: Is the light soft?\n")
    data = bench.run(spec, ["good one", "bad one", "fine"], Refusing(), Judge(), tmp_path, faces=None)
    assert [i["prompt"] for i in data["items"]] == ["good one", "fine"]
    assert data["skipped"][0]["prompt"] == "bad one"
    assert "bad one" in bench.to_markdown(bench.summarise(data, spec), spec)
