from crbench.config import Prompting
from crbench.prompt import build_prompt, extract_json_object, finding_text, numbered, parse_findings


def test_parse_plain_and_fenced():
    text = '{"findings": [{"file": "a.py", "line": "12", "severity": "High", "category": "Bug", "title": "t", "body": "b"}]}'
    assert parse_findings(text)[0] == {"index": 0, "file": "a.py", "line": 12, "severity": "high", "category": "bug", "title": "t", "body": "b"}
    fenced = "Here you go:\n```json\n" + text + "\n```\n"
    assert len(parse_findings(fenced)) == 1


def test_parse_empty_and_invalid():
    assert parse_findings('{"findings": []}') == []
    assert parse_findings("no json here") is None
    assert parse_findings('{"other": 1}') is None


def test_parse_skips_empty_and_odd_entries():
    text = '{"findings": [{"file": "a"}, "x", {"body": "only body", "line": "n/a", "category": "weird"}]}'
    out = parse_findings(text)
    assert len(out) == 1 and out[0]["line"] is None and out[0]["category"] == "weird"


def test_extract_widest_object():
    assert extract_json_object('prefix {"a": {"b": 1}} suffix') == {"a": {"b": 1}}


def test_finding_text():
    assert finding_text({"title": "T", "body": "B"}) == "T\n\nB"
    assert finding_text({"title": "T", "body": "T and more"}) == "T and more"
    assert finding_text({"title": "", "body": "B"}) == "B"


def test_numbered():
    assert numbered("a\nb") == "1 | a\n2 | b"


def test_build_prompt_budget():
    pr = {"title": "t", "source_repo": "r", "language": "Go", "base_sha": "b", "head_sha": "h", "description": "",
          "files": [{"path": "big.go", "status": "modified", "additions": 1, "deletions": 0, "patch": "@@\n+x", "content": "x" * 50},
                    {"path": "small.go", "status": "modified", "additions": 1, "deletions": 0, "patch": "p" * 30, "content": "y" * 10},
                    {"path": "img.png", "status": "added", "additions": 0, "deletions": 0, "patch": None, "content": None}]}
    cfg = Prompting(system=None, user=None, file_chars_max=40, files_chars_budget=100, patch_chars_max=20)
    p = build_prompt(pr, cfg, "SYS", "{title}|{file_table}|{files}|{description}|{file_count}|{repo}|{language}|{base_sha}|{head_sha}")
    assert "big.go" in p.patch_only and "img.png" in p.patch_only and "small.go" not in p.patch_only
    assert p.cut_patches == ["small.go"]
    assert "(no description)" in p.user and "(no textual diff" in p.user
    assert len(p.sha) == 16


def test_reasoning_with_braces_before_the_json():
    text = ("Looking at this PR: `useEffect(() => { prime(); }, [])` runs once.\n\n```json\n"
            '{"findings": [{"file": "a.ts", "line": 3, "severity": "low", "category": "bug", "title": "T", "body": "B"}]}\n```')
    out = parse_findings(text)
    assert out is not None and len(out) == 1 and out[0]["file"] == "a.ts"


def test_salvage_repairs_escapes_and_keeps_complete_findings():
    import json

    from crbench.prompt import repair_escapes, salvage_findings
    assert json.loads(repair_escapes(r'{"t": "a \` b \\ c \n d \"q\""}')) == {"t": 'a ` b \\ c \n d "q"'}
    bad_escape = r'{"findings": [{"file": "a.ts", "line": 3, "title": "T", "body": "createRelativeUrl(\`/x\`)"}]}'
    assert parse_findings(bad_escape) is None and [f["file"] for f in salvage_findings(bad_escape)] == ["a.ts"]
    cut = r'{"findings": [{"file": "a.py", "title": "One", "body": "x"}, {"file": "b.py", "title": "Two", "body": "z"}, {"file": "c.py", "title": "Thr'
    assert [f["title"] for f in salvage_findings(cut)] == ["One", "Two"]
    assert salvage_findings("") is None and salvage_findings("no json at all") is None
