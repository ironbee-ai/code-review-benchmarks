"""A local chat-completions endpoint for the benchmark's steps. The steps are pointed at
http://127.0.0.1:<port>/j/<judge>/<step>/<tool>/v1; the proxy sends each call to the judge's route with the judge's
key (the steps never see a key), adds the judge's params, removes the ones it drops, and appends one usage row per
call to results/judge_usage/<judge>.jsonl (step, tool, tokens, the cost the provider reported, latency, status).
A judge on the bedrock-anthropic route has no chat-completions endpoint: its calls are turned into Messages API
requests and the replies back into the chat-completions shape the steps read."""
from __future__ import annotations

import json
import random
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

from .config import Judge
from .env import ROOT, region, require
from .providers.openai_compat import OPENROUTER_URL, read_usage

USAGE_DIR = ROOT / "results" / "judge_usage"
IN_FLIGHT_WAIT_S = 10   # how long a call refused for OpenRouter's in-flight budget is held and asked again (the step waits 30 s)


def route_target(route: str) -> tuple[str, str]:
    if route == "bedrock-anthropic":
        return f"https://bedrock-runtime.{region()}.amazonaws.com/anthropic", require("AWS_BEARER_TOKEN_BEDROCK")
    if route == "openrouter":
        return OPENROUTER_URL, require("OPENROUTER_API_KEY")
    if route == "bedrock-openai":
        return f"https://bedrock-runtime.{region()}.amazonaws.com/openai/v1", require("AWS_BEARER_TOKEN_BEDROCK")
    raise ValueError(f"route {route!r} has no chat-completions endpoint")


def shape_body(body: dict, judge: Judge) -> dict:
    out = {k: v for k, v in body.items() if k not in set(judge.drop) | {"stream", "stream_options"}}
    out["model"] = judge.model
    for k, v in judge.params.items():
        out[k] = v
    if judge.route == "bedrock-openai":
        out.pop("provider", None)
        out.pop("reasoning", None)
    return out


def to_messages(body: dict, judge: Judge) -> dict:
    """A chat-completions request as a Messages API request: system messages joined into `system`, the rest as turns."""
    system = "\n\n".join(m.get("content") or "" for m in body.get("messages", []) if m.get("role") == "system")
    turns = [{"role": m["role"], "content": m.get("content") or ""} for m in body.get("messages", []) if m.get("role") in ("user", "assistant")]
    out: dict = {"model": judge.model, "max_tokens": int(body.get("max_tokens") or body.get("max_completion_tokens") or 4096), "messages": turns}
    if system:
        out["system"] = system
    if body.get("temperature") is not None and "temperature" not in judge.drop:
        out["temperature"] = body["temperature"]
    if judge.params.get("effort"):
        out["output_config"] = {"effort": judge.params["effort"]}
    return out


class _Server(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        """A step stopped mid-request (Ctrl-C) leaves a reset connection: nothing to report."""
        if not isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            super().handle_error(request, client_address)


def from_messages(msg: dict) -> dict:
    """A Messages API reply in the chat-completions shape, usage included."""
    text = "".join(b.get("text", "") for b in msg.get("content", []) if b.get("type") == "text")
    u = msg.get("usage") or {}
    cached = int(u.get("cache_read_input_tokens") or 0)
    prompt = int(u.get("input_tokens") or 0) + cached + int(u.get("cache_creation_input_tokens") or 0)
    return {"id": msg.get("id"), "object": "chat.completion", "model": msg.get("model"),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": msg.get("stop_reason")}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": int(u.get("output_tokens") or 0),
                      "prompt_tokens_details": {"cached_tokens": cached, "cache_write_tokens": int(u.get("cache_creation_input_tokens") or 0)}}}


def parse_path(path: str) -> tuple[str, str, str, str] | None:
    """/j/<judge>/<step>/<tool>/v1/chat/completions -> (judge, step, tool, rest)."""
    parts = path.split("/")
    if len(parts) < 7 or parts[1] != "j":
        return None
    return parts[2], parts[3], parts[4], "/".join(parts[5:])


def _step_parse(content: str):
    """The benchmark's steps' own parse: strip one code fence, then json.loads."""
    content = content.strip()
    if content.startswith("```"):
        parts = content.split("```")
        content = (parts[1] if len(parts) > 1 else content).removeprefix("json").strip()
    return json.loads(content)


def in_flight_refusal(status: int, payload: bytes) -> bool:
    """OpenRouter's 402 for a balance that covers the account but not the requests in flight (it reserves each one's
    possible cost; 2026-10-18, at ~$9 left with ~150 judge calls in flight). It clears as soon as calls finish."""
    return status == 402 and b"in_flight_budget_exhausted" in payload


def last_json_object(text: str) -> dict | None:
    """The last top-level JSON object in a text (prose may hold braces of its own, e.g. Ruby's #{h})."""
    dec, i, found = json.JSONDecoder(), 0, None
    while (i := text.find("{", i)) != -1:
        try:
            obj, end = dec.raw_decode(text, i)
        except ValueError:
            i += 1
            continue
        if isinstance(obj, dict):
            found = obj
        i = end
    return found


def _retype(verdict: dict) -> bool:
    """A verdict with "confidence": "0.9" crashes the benchmark's step (a string compared with a number; Grok 4.7 at low
    effort, 2026-10-18), and one with "match": "false" would count as a match ("false" is truthy). Both are given the
    types the step expects; the verdict stays the judge's own. Returns whether anything changed."""
    changed = False
    m = verdict.get("match")
    if isinstance(m, str):
        verdict["match"] = m.strip().lower() in ("true", "yes", "1")
        changed = True
    c = verdict.get("confidence")
    if isinstance(c, str):
        s = c.strip()
        try:
            verdict["confidence"] = float(s.rstrip("%")) / (100 if s.endswith("%") else 1)
        except ValueError:
            verdict["confidence"] = 0.0
        changed = True
    return changed


def normalize_reply(payload: bytes) -> tuple[bytes, bool]:
    """A judge that writes its reasoning before the JSON (Opus 5.5 at low effort, on ambiguous pairs) makes the step's
    parse fail on every retry. When the step could not parse the reply, the reply's last JSON object becomes its
    content; the verdict is the judge's own. A verdict whose match or confidence is a string is retyped (_retype).
    Returns the payload and whether it was changed."""
    try:
        data = json.loads(payload)
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        return payload, False
    try:
        obj = _step_parse(content or "")
    except ValueError:
        obj = last_json_object(content or "")
        if obj is None:
            return payload, False
        _retype(obj)
    else:
        if not (isinstance(obj, dict) and _retype(obj)):
            return payload, False
    data["choices"][0]["message"]["content"] = json.dumps(obj)
    return json.dumps(data).encode(), True


def reply_is_object(payload: bytes) -> bool:
    """Whether a judge's reply holds the JSON object the benchmark's steps parse (after their own fence stripping). A
    reply that is valid JSON but not an object (a bare number) crashes the step instead of being asked again."""
    try:
        content = json.loads(payload)["choices"][0]["message"]["content"].strip()
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return False
    if content.startswith("```"):
        parts = content.split("```")
        content = parts[1] if len(parts) > 1 else content
        content = content.removeprefix("json")
        content = content.strip()
    try:
        return isinstance(json.loads(content), dict)
    except ValueError:
        return True          # not JSON at all: the step's own parse-and-retry handles it


def new_client() -> httpx.Client:
    """An upstream client for one incoming connection (one handler thread). Until 2026-10-18 the proxy shared one
    client across its ~200 handler threads: httpcore 1.0.9's pool closes a connection it counts as surplus idle
    (`len([c.is_idle() for c in connections])` counts every connection, not the idle ones) even when it has just been
    handed to another thread, which then reads a closed socket ("Bad file descriptor") or, once the descriptor is
    reused, writes TLS records into whatever was opened next (seen in a usage log). A client per connection is used
    by one thread only."""
    return httpx.Client(timeout=httpx.Timeout(180, connect=15))


class JudgeProxy:
    def __init__(self, judges: dict[str, Judge], port: int = 0):
        self.judges = judges
        self.targets = {jid: route_target(j.route) for jid, j in judges.items()}
        self.new_client = new_client
        self.lock = threading.Lock()
        self.logs: dict = {}  # judge id -> its usage log, opened once
        USAGE_DIR.mkdir(parents=True, exist_ok=True)
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            upstream = None

            def log_message(self, *args):  # quiet
                return

            def do_POST(self):
                proxy.handle(self)

            def finish(self):
                try:
                    super().finish()
                finally:
                    if self.upstream is not None:
                        self.upstream.close()

        self.server = _Server(("127.0.0.1", port), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def base_url(self, judge_id: str, step: str, tool: str) -> str:
        return f"http://127.0.0.1:{self.port}/j/{judge_id}/{step}/{tool}/v1"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        with self.lock:
            for f in self.logs.values():
                f.close()
            self.logs.clear()

    def _log(self, jid: str, row: dict) -> None:
        with self.lock:
            f = self.logs.get(jid)
            if f is None:
                f = self.logs[jid] = open(USAGE_DIR / f"{jid}.jsonl", "a")  # noqa: SIM115 -- kept open while the proxy runs, closed on exit
            f.write(json.dumps(row) + "\n")
            f.flush()

    def _reply(self, h: BaseHTTPRequestHandler, status: int, payload: bytes) -> None:
        try:
            h.send_response(status)
            h.send_header("Content-Type", "application/json")
            h.send_header("Content-Length", str(len(payload)))
            h.end_headers()
            h.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass             # the step gave up waiting (its 30 s per call) and will ask again

    def handle(self, h: BaseHTTPRequestHandler) -> None:
        parsed = parse_path(h.path)
        length = int(h.headers.get("Content-Length") or 0)
        raw = h.rfile.read(length) if length else b"{}"
        if parsed is None or parsed[0] not in self.judges or not parsed[3].endswith("chat/completions"):
            self._reply(h, 404, json.dumps({"error": {"message": f"unknown path {h.path}"}}).encode())
            return
        jid, step, tool, _ = parsed
        judge = self.judges[jid]
        base, key = self.targets[jid]
        try:
            body = shape_body(json.loads(raw or b"{}"), judge)
        except ValueError:
            self._reply(h, 400, b'{"error":{"message":"bad json"}}')
            return
        if getattr(h, "upstream", None) is None:
            h.upstream = self.new_client()
        client = h.upstream
        t0 = time.time()
        status, payload, usage, cost, served, normalized, waited = 502, b"", None, None, None, False, 0
        try:
            if judge.route == "bedrock-anthropic":
                r = client.post(f"{base}/v1/messages", json=to_messages(json.loads(raw or b"{}"), judge),
                                     headers={"x-api-key": key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"})
                status, payload = r.status_code, (json.dumps(from_messages(r.json())).encode() if r.status_code == 200 else r.content)
            else:
                while True:   # a call refused for the in-flight budget waits for others to finish instead of failing its review
                    r = client.post(f"{base}/chat/completions", json=body, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
                    status, payload = r.status_code, r.content
                    if not in_flight_refusal(status, payload) or time.time() - t0 > IN_FLIGHT_WAIT_S:
                        break
                    waited += 1
                    time.sleep(1 + random.random())
            if status == 200:
                data = json.loads(payload)
                usage = data.get("usage")
                cost = (usage or {}).get("cost")
                served = data.get("model")
                payload, normalized = normalize_reply(payload)
                if not reply_is_object(payload):
                    status, payload = 502, json.dumps({"error": {"message": "proxy: the judge's reply is JSON but not an object"}}).encode()
        except httpx.HTTPError as e:
            payload = json.dumps({"error": {"message": f"proxy: {type(e).__name__}: {str(e)[:300]}"}}).encode()
        row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "judge": jid, "step": step, "tool": tool, "status": status,
               "latency_ms": int((time.time() - t0) * 1000), "usage": read_usage(usage) if usage else None,
               "cost_reported": float(cost) if isinstance(cost, (int, float)) else None, "served_model": served,
               "error": payload[:300].decode("utf-8", "replace") if status != 200 else None, "client_gone": False,
               "normalized": normalized, "in_flight_waits": waited}
        self._log(jid, row)
        self._reply(h, status, payload)
