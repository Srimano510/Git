"""A tiny OpenAI-compatible mock LLM for the demo (a fallback when the real model is down).

    uv run python -m scripts.mock_llm [--port 18999] [--log requests.jsonl]

Point the demo config at it (`providers.openai.apiBase = http://127.0.0.1:18999/v1`, any key).
It is deterministic and **context-sensitive**: it answers a question only from facts that are
present in the request it receives (the history and the system prompt, including a
"[Recalled Context]" block), and says what it cannot find otherwise. So linear, graph and hybrid
visibly give different answers to the same question, even without a real model. Every answer is
prefixed "(mock LLM)" so nobody mistakes it for the real thing. It also answers the WebUI's
title requests and `/context summarize` requests, and logs each request as a JSON line.
"""

from __future__ import annotations

import argparse
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

PREFIX = "(mock LLM) "

# fact key -> (what the context must contain, the sentence it supports, what is missing otherwise)
FACTS = {
    "database": (r"postgres", "The orders service uses Postgres.", "which database the orders service uses"),
    "deploy": (r"fly\.io", "It is deployed to Fly.io in Frankfurt.", "where it is deployed"),
    "synergy": (
        r"typed edges|synergy",
        "Graphs give structure through typed edges and vectors give fuzzy recall of old facts.",
        "how graphs and vectors complement each other",
    ),
}
# fact key -> what in the question asks for it
QUESTIONS = {
    "database": r"\bdatabase\b|\bdb\b",
    "deploy": r"\bdeploy|\bhosted\b|where .*\brun",
    "synergy": r"graphs?\b.*\bvectors?\b|vectors?\b.*\bgraphs?\b|complement",
}


def _text(content: Any) -> str:
    if isinstance(content, list):
        blocks: list[Any] = content  # type: ignore[assignment]
        return " ".join(str(b.get("text", "")) for b in blocks if isinstance(b, dict))  # type: ignore[union-attr]
    return str(content or "")


def respond(messages: list[dict[str, Any]]) -> str:
    """The reply to a chat request: title, summary, or an answer from the context present."""
    users = [m for m in messages if m.get("role") == "user"]
    last: dict[str, Any] = users[-1] if users else {}
    prompt = _text(last.get("content"))

    if prompt.startswith("Generate a concise title"):
        user = prompt.split("User:", 1)[-1].split("\nAssistant:", 1)[0]
        return " ".join(user.split()[:5]) or "New chat"

    if "Transcript:\n" in prompt:
        lines = [ln for ln in prompt.split("Transcript:\n", 1)[1].splitlines() if ln.strip()]
        asked = [ln[6:].strip()[:60] for ln in lines if ln.startswith("user: ")][:3]
        return f"{PREFIX}Summary of {len(lines)} messages. The user asked: {'; '.join(asked) or 'nothing'}."

    # the context is everything the model was given except the question being answered
    context = "\n".join(_text(m.get("content")) for m in messages if m is not last).lower()
    wanted = [k for k, pattern in QUESTIONS.items() if re.search(pattern, prompt.lower())]
    if not wanted:
        return f"{PREFIX}Noted."
    parts: list[str] = []
    for key in wanted:
        needs, sentence, missing = FACTS[key]
        parts.append(sentence if re.search(needs, context) else f"I can't find {missing} in the context I was given.")
    return PREFIX + " ".join(parts)


def _tokens(text: str) -> int:
    return max(1, len(text.split()))


def make_server(port: int, log_path: Path | None = None) -> ThreadingHTTPServer:
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002  (quiet)
            pass

        def _send(self, status: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path.rstrip("/").endswith("/models"):
                data = {"object": "list", "data": [{"id": "mock-demo", "object": "model"}]}
                self._send(200, json.dumps(data).encode())
            else:
                self._send(200, b'{"status":"ok"}')

        def do_POST(self) -> None:  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if log_path is not None:
                with lock, log_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({**body, "_time": time.time()}) + "\n")
            text = respond(body.get("messages", []))
            usage = {"prompt_tokens": 10, "completion_tokens": _tokens(text), "total_tokens": 10 + _tokens(text)}
            model = body.get("model", "mock-demo")
            if not body.get("stream"):
                out = {
                    "id": "mock", "object": "chat.completion", "model": model, "usage": usage,
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                }
                self._send(200, json.dumps(out).encode())
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()

            def chunk(delta: dict[str, Any], finish: str | None = None, **extra: Any) -> None:
                event = {"id": "mock", "object": "chat.completion.chunk", "model": model,
                         "choices": [{"index": 0, "delta": delta, "finish_reason": finish}], **extra}
                self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())

            chunk({"role": "assistant", "content": ""})
            for piece in re.findall(r"\S+\s*", text):
                chunk({"content": piece})
            chunk({}, "stop", usage=usage)
            self.wfile.write(b"data: [DONE]\n\n")

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--port", type=int, default=18999)
    parser.add_argument("--log", type=Path, help="append each request as a JSON line")
    args = parser.parse_args(argv)
    server = make_server(args.port, args.log)
    print(f"mock LLM on http://127.0.0.1:{args.port}/v1 (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
