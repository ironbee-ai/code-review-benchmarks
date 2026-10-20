from crbench.config import Judge
from crbench.judge_proxy import normalize_reply, parse_path, shape_body
from crbench.lane import candidates_of, restore_broken, review_of, snapshot


def test_review_and_candidates_share_text():
    run = {"pr_id": "x__1", "golden_url": "u", "run_id": "r", "findings": [{"file": "a.py", "line": 3, "title": "T", "body": "B"}, {"file": "b", "title": "", "body": ""}]}
    rv = review_of("tool", run)
    cands = candidates_of(run)
    assert rv["review_comments"][0]["body"] == cands[0]["text"] == "T\n\nB"
    assert len(cands) == 1 and len(rv["review_comments"]) == 2


def test_proxy_path_and_body():
    assert parse_path("/j/gemini/step3/m__default__r1/v1/chat/completions") == ("gemini", "step3", "m__default__r1", "v1/chat/completions")
    assert parse_path("/v1/chat/completions") is None
    j = Judge("sol", "openai", "bedrock-openai", "global.openai.gpt-6.1-sol", params={"reasoning_effort": "low"}, drop=["temperature"])
    b = shape_body({"model": "x", "temperature": 0.0, "messages": [], "stream": True}, j)
    assert b == {"model": "global.openai.gpt-6.1-sol", "messages": [], "reasoning_effort": "low"}
    j2 = Judge("g", "google", "openrouter", "google/gemini-4-argon", params={"reasoning": {"effort": "low"}})
    assert shape_body({"temperature": 0.0, "messages": []}, j2)["temperature"] == 0.0


def test_inject_drops_stale_judge_rows(tmp_path):
    import json

    from crbench.lane import inject
    j = Judge("g", "google", "openrouter", "google/gemini-4-argon")
    lane = tmp_path / "offline"
    (lane / "results" / j.model_dir).mkdir(parents=True)
    (lane / "results" / "benchmark_data.json").write_text(json.dumps({"u": {"golden_comments": [], "reviews": [{"tool": "t", "review_comments": []}]}}))
    run = {"pr_id": "p", "golden_url": "u", "status": "ok", "findings": [{"title": "A", "body": "a"}]}
    inject(lane, j, "t", [run])
    ev = lane / "results" / j.model_dir / "evaluations.json"
    ev.write_text(json.dumps({"u": {"t": {"tp": 1}}}))
    inject(lane, j, "t", [run])                       # same candidates: the judged row stays
    assert json.loads(ev.read_text())["u"]["t"] == {"tp": 1}
    run2 = {**run, "findings": [{"title": "B", "body": "b"}]}
    inject(lane, j, "t", [run2])                      # new candidates: the row goes
    assert "t" not in json.loads(ev.read_text())["u"]
    bench = json.loads((lane / "results" / "benchmark_data.json").read_text())
    assert len(bench["u"]["reviews"]) == 1 and bench["u"]["reviews"][0]["review_comments"][0]["body"] == "B\n\nb"


def test_reply_is_object():
    import json

    from crbench.judge_proxy import reply_is_object
    wrap = lambda c: json.dumps({"choices": [{"message": {"content": c}}]}).encode()
    assert reply_is_object(wrap('{"match": true}'))
    assert reply_is_object(wrap('```json\n{"match": false}\n```'))
    assert not reply_is_object(wrap("1"))
    assert reply_is_object(wrap("not json at all"))
    assert not reply_is_object(b"{}")


def test_a_step_cut_short_is_restored(tmp_path):
    judge = Judge(id="j", family="f", route="openrouter", model="vendor/model")
    d = tmp_path / "results" / judge.model_dir
    d.mkdir(parents=True)
    (d / "evaluations.json").write_text('{"u": {"t": {"errors_count": 0}}}')
    snapshot(tmp_path, judge)
    (d / "evaluations.json").write_text('{"u": {"t": {"errors_co')   # the step was killed while saving
    assert restore_broken(tmp_path, judge) == ["evaluations.json"]
    assert (d / "evaluations.json").read_text() == '{"u": {"t": {"errors_count": 0}}}'
    assert restore_broken(tmp_path, judge) == []


def test_reasoning_before_the_json_is_normalized():
    import json
    prose = ("The golden names the controller, but the `'#{h}'` interpolation is in the migration; same issue.\n\n"
             '```json\n{"reasoning": "same SQL injection", "match": true, "confidence": 0.8}\n```')
    wrap = lambda c: json.dumps({"choices": [{"message": {"content": c}}]}).encode()
    out, changed = normalize_reply(wrap(prose))
    assert changed and json.loads(json.loads(out)["choices"][0]["message"]["content"])["match"] is True
    plain = wrap('{"reasoning": "r", "match": false, "confidence": 0.9}')
    assert normalize_reply(plain) == (plain, False)                      # what the step parses stays as it is
    fenced = wrap('```json\n{"match": true}\n```')
    assert normalize_reply(fenced) == (fenced, False)
    assert normalize_reply(wrap("no json here"))[1] is False


def test_string_match_and_confidence_are_retyped():
    import json
    wrap = lambda c: json.dumps({"choices": [{"message": {"content": c}}]}).encode()
    verdict = lambda b: json.loads(json.loads(normalize_reply(b)[0])["choices"][0]["message"]["content"])
    v = verdict(wrap('{"reasoning": "r", "match": true, "confidence": "0.9"}'))          # crashed the step (Grok, 2026-10-18)
    assert v["match"] is True and v["confidence"] == 0.9
    assert verdict(wrap('{"match": "false", "confidence": 0.8}'))["match"] is False      # "false" is truthy to the step
    assert verdict(wrap('```json\n{"match": "True", "confidence": "85%"}\n```')) == {"match": True, "confidence": 0.85}
    assert verdict(wrap('{"match": true, "confidence": "high"}'))["confidence"] == 0.0
    assert verdict(wrap('Same issue.\n{"match": "yes", "confidence": "0.7"}')) == {"match": True, "confidence": 0.7}


def test_in_flight_refusal_waits_and_asks_again(tmp_path, monkeypatch):
    import json

    import httpx

    import crbench.judge_proxy as JP
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(JP, "USAGE_DIR", tmp_path)
    monkeypatch.setattr(JP.time, "sleep", lambda s: None)
    refusal = json.dumps({"error": {"code": 402, "metadata": {"reason": "in_flight_budget_exhausted"}}}).encode()
    ok = json.dumps({"model": "m", "choices": [{"message": {"content": '{"match": true, "confidence": 0.9}'}}]}).encode()
    replies = [(402, refusal), (402, refusal), (200, ok)]
    j = Judge("g", "google", "openrouter", "google/gemini-4-argon")
    with JP.JudgeProxy({"g": j}) as proxy:
        def reply(req):
            status, content = replies.pop(0)
            return httpx.Response(status, content=content)

        proxy.new_client = lambda: httpx.Client(transport=httpx.MockTransport(reply))
        r = httpx.post(proxy.base_url("g", "step3", "t__r2") + "/chat/completions", json={"messages": []})
    assert r.status_code == 200 and not replies
    row = json.loads((tmp_path / "g.jsonl").read_text())
    assert row["status"] == 200 and row["in_flight_waits"] == 2
    assert not JP.in_flight_refusal(402, b'{"error": {"message": "Insufficient credits"}}')   # an empty account is not waited on


def test_each_connection_has_its_own_upstream_client(tmp_path, monkeypatch):
    import json
    import threading

    import httpx

    import crbench.judge_proxy as JP
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(JP, "USAGE_DIR", tmp_path)
    ok = json.dumps({"model": "m", "choices": [{"message": {"content": '{"match": false, "confidence": 0.9}'}}]}).encode()
    made, closed, users = [], [], {}

    class Tracked(httpx.Client):
        def close(self):
            closed.append(self)
            super().close()

    def factory():
        c = Tracked(transport=httpx.MockTransport(lambda req: (users.setdefault(id(c), set()).add(threading.get_ident()), httpx.Response(200, content=ok))[1]))
        made.append(c)
        return c
    j = Judge("g", "google", "openrouter", "google/gemini-4-argon")
    with JP.JudgeProxy({"g": j}) as proxy:
        proxy.new_client = factory
        url = proxy.base_url("g", "step3", "t__r2") + "/chat/completions"
        with httpx.Client() as a, httpx.Client() as b:          # two keep-alive connections, two requests each
            for _ in range(2):
                assert a.post(url, json={"messages": []}).status_code == 200
                assert b.post(url, json={"messages": []}).status_code == 200
    assert len(made) == 2 and all(len(t) == 1 for t in users.values())   # one client per connection, one thread each
    assert set(map(id, closed)) == set(map(id, made))                     # closed when its connection ends
    assert len((tmp_path / "g.jsonl").read_text().splitlines()) == 4


def test_lane_review_timeout(tmp_path):
    """Lanes allow a review 90 minutes in the benchmark's judging step (its own limit is 30), every time they are made."""
    from crbench import lane as L

    step = tmp_path / "code_review_benchmark" / "step3_judge_comments.py"
    step.parent.mkdir()
    step.write_text("LLM_CALL_TIMEOUT = 30\nREVIEW_TIMEOUT = 1800  # seconds per full review evaluation (30 min)\n")
    L._set_review_timeout(tmp_path)
    L._set_review_timeout(tmp_path)
    lines = step.read_text().splitlines()
    assert lines[0] == "LLM_CALL_TIMEOUT = 30"
    assert lines[1].startswith(f"REVIEW_TIMEOUT = {L.REVIEW_TIMEOUT_S} ")
