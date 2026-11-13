#!/usr/bin/env python3
"""OpenAI-compatible proxy that injects Recuris working memory into TB8 runs.

This is the m0-gate arm: a fixed Skill Memory package (default
``skill_memories/tb21_seed``) is seeded once per task, its rendered working
memory is appended to the system prompt before each model request, and the
Recuris ``check_completion`` gate can bounce a premature final answer by
injecting a synthetic ``bash`` tool call that prints the correction.  It does
NOT implement the meta-agent patch loop (the ``tta`` memory update).

    python experiments/tb-eval/adapters/recuris/proxy.py \
        --memory .cache/upstream/recuris/skill_memories/tb21_seed \
        --port 8081 --upstream http://127.0.0.1:8080 \
        --log .cache/recuris-adapter.jsonl

Then run the Pi-only runner with HW_MODEL_URL=http://127.0.0.1:8081.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import time
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(REPO / ".cache" / "upstream" / "recuris" / "src"))

from recuris.adapters.tb21.runtime_bridge import TerminalSkillBridge  # noqa: E402

MAX_BOUNCES = 3
STATE = {
    "bridge": None,
    "instruction": "",
    "base_system": None,
    "turn": 0,
    "observed": set(),
    "bounces": 0,
    "task": "",
}


def text_of(message):
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


def find_instruction(messages):
    for message in messages:
        if message.get("role") == "user" and text_of(message).strip():
            return text_of(message).strip()
    return ""


def reset_bridge(memory: Path, instruction: str, task: str = ""):
    bridge = TerminalSkillBridge(str(memory), "")
    bridge.start(instruction)
    STATE.update(bridge=bridge, instruction=instruction, base_system=None, turn=0,
                 observed=set(), bounces=0, task=task)


def tool_call_command(call):
    function = call.get("function") or {}
    if function.get("name") != "bash":
        return None
    try:
        args = json.loads(function.get("arguments") or "{}")
    except json.JSONDecodeError:
        return None
    command = args.get("command")
    return command if isinstance(command, str) and command.strip() else None


def observe_new_tool_calls(messages):
    """Feed the bridge the bash receipts already present in the conversation."""
    bridge = STATE["bridge"]
    if bridge is None:
        return
    observed = STATE["observed"]
    outputs = {
        message.get("tool_call_id"): text_of(message)
        for message in messages
        if message.get("role") == "tool" and message.get("tool_call_id")
    }
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or []:
            call_id = call.get("id") or call.get("tool_call_id")
            if not call_id or call_id in observed:
                continue
            command = tool_call_command(call)
            if command is None:
                observed.add(call_id)
                continue
            bridge.observe_commands(
                [SimpleNamespace(keystrokes=command)],
                outputs.get(call_id, ""),
                timed_out=False,
            )
            observed.add(call_id)


def parse_sse(body: bytes):
    content, has_tool, finish = [], False, None
    for line in body.decode("utf-8", "replace").splitlines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            continue
        try:
            obj = json.loads(data)
        except json.JSONDecodeError:
            continue
        for choice in obj.get("choices", []):
            delta = choice.get("delta") or {}
            if delta.get("content"):
                content.append(delta["content"])
            if delta.get("tool_calls"):
                has_tool = True
            if choice.get("finish_reason"):
                finish = choice["finish_reason"]
    return "".join(content), has_tool, finish


def parse_json_response(body: bytes):
    try:
        obj = json.loads(body)
        choice = (obj.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        return message.get("content") or "", bool(message.get("tool_calls")), choice.get("finish_reason")
    except (json.JSONDecodeError, KeyError, TypeError):
        return "", False, None


def shell_print(text: str) -> str:
    # printf is a shell builtin; avoid base64/jq dependencies in task images.
    escaped = text.replace("\\", "\\\\").replace("'", "'\\''")
    return f"printf '%b' '{escaped}'"


def bounce_response(request, text, call_id, stream):
    command = shell_print(text)
    arguments = json.dumps({"command": command})
    model = request.get("model", "qwen3.5-9b")
    if stream:
        created = int(time.time())
        chunks = [
            {"id": "chatcmpl-recuris-bounce", "object": "chat.completion.chunk",
             "created": created, "model": model,
             "choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": [
                 {"index": 0, "id": call_id, "type": "function",
                  "function": {"name": "bash", "arguments": arguments}}]},
                 "finish_reason": None}]},
            {"id": "chatcmpl-recuris-bounce", "object": "chat.completion.chunk",
             "created": created, "model": model,
             "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
        ]
        body = "\n\n".join("data: " + json.dumps(chunk) for chunk in chunks)
        return (body + "\n\ndata: [DONE]\n\n").encode(), "text/event-stream"
    obj = {
        "id": "chatcmpl-recuris-bounce", "object": "chat.completion",
        "created": int(time.time()), "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": None,
                     "tool_calls": [{"id": call_id, "type": "function",
                                     "function": {"name": "bash", "arguments": arguments}}]},
                     "finish_reason": "tool_calls"}],
        "usage": {},
    }
    return json.dumps(obj).encode(), "application/json"


class Handler(BaseHTTPRequestHandler):
    server_version = "recuris-tb8-adapter/0.2"

    def log_message(self, fmt, *args):
        pass

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def _send(self, status: int, body: bytes, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, b'{"status":"ok"}')
            return
        self._send(404, b'{"error":"not found"}')

    def do_POST(self):
        if self.path == "/dump":
            out = Path(self.server.dump_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            bridge = STATE["bridge"]
            if bridge is not None:
                bridge.dump(out)
            self._send(200, json.dumps({"dumped": str(out)}).encode())
            return
        if self.path not in ("/v1/chat/completions", "/chat/completions"):
            self._send(404, b'{"error":"not found"}')
            return

        request = self._read_json()
        messages = request.get("messages", [])
        instruction = find_instruction(messages)
        task = self.headers.get("x-recuris-task") or ""
        if task:
            # The runner stamps every request with the case id.  Pi may rewrite
            # the first user message during compaction, so the id is the stable
            # boundary; only a new task resets the bridge.
            if task != STATE["task"]:
                reset_bridge(Path(self.server.memory), instruction, task)
        elif instruction and instruction != STATE["instruction"]:
            reset_bridge(Path(self.server.memory), instruction)

        bridge = STATE["bridge"]
        if bridge is not None:
            observe_new_tool_calls(messages)
        prompt_block = ""
        if bridge is not None:
            prompt_block = bridge.prepare_prompt("")
            STATE["turn"] += 1

        # Keep the original system prompt and replace the injected block each
        # turn, so blocks do not accumulate across requests.
        for message in messages:
            if message.get("role") == "system":
                if STATE["base_system"] is None:
                    STATE["base_system"] = text_of(message)
                message["content"] = STATE["base_system"] + "\n\n" + prompt_block
                break
        else:
            messages.insert(0, {"role": "system", "content": prompt_block})
        request["messages"] = messages
        payload = json.dumps(request).encode("utf-8")

        upstream = urlparse(self.server.upstream)
        conn = HTTPConnection(upstream.hostname, upstream.port or 80, timeout=330)
        headers = {"Content-Type": "application/json"}
        if self.headers.get("Authorization"):
            headers["Authorization"] = self.headers["Authorization"]
        bounced = False
        try:
            conn.request("POST", upstream.path.rstrip("/") + self.path, payload, headers)
            response = conn.getresponse()
            body = response.read()
            content_type = response.getheader("Content-Type", "application/json")
            if response.status == 200 and bridge is not None:
                if "text/event-stream" in content_type:
                    content, has_tool, finish = parse_sse(body)
                else:
                    content, has_tool, finish = parse_json_response(body)
                if not has_tool and finish == "stop" and content.strip():
                    bounce = bridge.check_completion([], content)
                    if bounce is not None and bridge.completion_blocks <= MAX_BOUNCES:
                        text = getattr(bounce, "correction", None) or getattr(bounce, "reason", "")
                        call_id = f"call_recuris_bounce_{bridge.completion_blocks}"
                        STATE["observed"].add(call_id)
                        body, content_type = bounce_response(request, str(text), call_id,
                                                             bool(request.get("stream")))
                        STATE["bounces"] += 1
                        bounced = True
            self._send(response.status, body, content_type)
            record = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "instruction_sha": hashlib.sha256(STATE["instruction"].encode()).hexdigest()[:16],
                "turn": STATE["turn"],
                "block_chars": len(prompt_block),
                "status": response.status,
                "response_bytes": len(body),
                "bounced": bounced,
                "bounces_total": STATE["bounces"],
            }
        except Exception as exc:  # noqa: BLE001
            record = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "turn": STATE["turn"],
                "error": f"{type(exc).__name__}: {exc}",
            }
            self._send(502, json.dumps({"error": record["error"]}).encode())
        finally:
            conn.close()
        if self.server.log_path:
            with open(self.server.log_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--memory", required=True, help="Skill Memory package directory")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--upstream", default="http://127.0.0.1:8080")
    parser.add_argument("--log", default="")
    parser.add_argument("--dump", default=".cache/recuris-adapter-fingerprint.json")
    args = parser.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.memory = args.memory
    server.upstream = args.upstream
    server.log_path = args.log
    server.dump_path = args.dump
    print(f"recuris adapter on 127.0.0.1:{args.port} -> {args.upstream}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
