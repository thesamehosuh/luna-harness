#!/usr/bin/env python3
"""OpenCode Go header shim.

OpenCode Go's Console relay rejects any request that lacks the
``x-opencode-session`` header (HTTP 400 ``MissingSessionID``). It is a routing /
prompt-cache affinity key, not a credential, so any stable per-conversation
string is valid.

Honcho's OpenAI client cannot send custom headers (its config surface has no
header field and the backend only forwards top_p / penalties / seed through
``provider_params``), so this shim sits in front of the relay, adds the header,
and forwards everything else untouched.

Usage:
    opencode_go_proxy.py --port 8010 --upstream https://opencode.ai/zen/go/v1 \
        --session-key honcho

Then point Honcho at http://127.0.0.1:8010/v1 (see config.toml).

Outbound traffic honours HTTP_PROXY / HTTPS_PROXY (needed on censored
networks); the shim tunnels through them with CONNECT.
"""

from __future__ import annotations

import argparse
import http.client
import http.server
import json
import os
import socketserver
import sys
import urllib.parse

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}

SESSION_HEADER = "x-opencode-session"


def parse_proxy(raw: str | None) -> tuple[str, int] | None:
    if not raw:
        return None
    parsed = urllib.parse.urlsplit(raw if "://" in raw else f"http://{raw}")
    if not parsed.hostname:
        return None
    return parsed.hostname, parsed.port or 8080


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    upstream_scheme = "https"
    upstream_host = "opencode.ai"
    upstream_port = 443
    upstream_prefix = "/zen/go/v1"
    session_key = "honcho"
    rewrite_schema = True
    proxy: tuple[str, int] | None = None
    timeout = 600.0

    # ---- logging -------------------------------------------------------
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        sys.stderr.write("go-shim %s %s\n" % (self.address_string(), fmt % args))
        sys.stderr.flush()

    # ---- plumbing ------------------------------------------------------
    def _connect(self) -> http.client.HTTPSConnection:
        if self.upstream_scheme == "http":
            return http.client.HTTPConnection(self.upstream_host, self.upstream_port, timeout=self.timeout)
        conn = http.client.HTTPSConnection(self.upstream_host, self.upstream_port, timeout=self.timeout)
        if self.proxy:
            conn.set_tunnel(self.proxy[0], self.proxy[1])
        return conn

    def _is_health(self) -> bool:
        return self.path.split("?")[0] in ("/health", "/healthz")

    def _downgrade_response_format(self, body: bytes) -> bytes:
        """OpenCode Go rejects ``json_schema`` response_format for some models
        (deepseek-v4.1-flash: "This response_format type is unavailable now").

        Rewrite it to ``json_object`` and hand the schema to the model as an
        instruction, so callers that rely on structured output still work.
        """
        if not body or not self.rewrite_schema:
            return body
        try:
            payload = json.loads(body)
        except Exception:  # noqa: BLE001
            return body
        if not isinstance(payload, dict):
            return body
        fmt = payload.get("response_format")
        if not isinstance(fmt, dict) or fmt.get("type") != "json_schema":
            return body

        spec = fmt.get("json_schema") or {}
        name = spec.get("name") or "response"
        schema = spec.get("schema") or {}
        instruction = (
            "Respond with ONLY one JSON object that validates against this JSON schema "
            f"(name: {name}). No markdown fences, no prose, no comments.\n{json.dumps(schema, ensure_ascii=False)}"
        )
        payload["response_format"] = {"type": "json_object"}

        messages = payload.get("messages")
        injected = False
        if isinstance(messages, list) and messages and isinstance(messages[-1], dict):
            content = messages[-1].get("content")
            if isinstance(content, str):
                messages[-1]["content"] = f"{content}\n\n{instruction}"
                injected = True
        if not injected:
            payload["messages"] = list(messages or []) + [{"role": "user", "content": instruction}]

        self.log_message("rewrote response_format json_schema(%s) -> json_object", name)
        return json.dumps(payload).encode()

    def _forward(self, method: str) -> None:
        if self._is_health():
            payload = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        body = self._downgrade_response_format(body)

        path = self.upstream_prefix + self.path
        headers: dict[str, str] = {}
        for key, value in self.headers.items():
            lowered = key.lower()
            if lowered in HOP_BY_HOP or lowered in ("host", "content-length"):
                continue
            headers[key] = value
        # Client-supplied affinity wins; otherwise pin this request.
        if not any(k.lower() == SESSION_HEADER for k in headers):
            headers[SESSION_HEADER] = self.session_key
        if body is not None:
            headers["Content-Length"] = str(len(body))
        headers.setdefault("Connection", "close")

        conn = self._connect()
        try:
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            payload = resp.read()

            self.send_response(resp.status)
            for key, value in resp.getheaders():
                if key.lower() in HOP_BY_HOP or key.lower() == "content-length":
                    continue
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            self.wfile.flush()
        except Exception as exc:  # noqa: BLE001
            import traceback

            traceback.print_exc()
            self.log_message("upstream error: %s: %s", type(exc).__name__, exc)
            payload = ('{"error":{"message":"go-shim upstream failure: %s"}}' % type(exc).__name__).encode()
            try:
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except Exception:  # noqa: BLE001
                pass
        finally:
            conn.close()

    def do_GET(self) -> None:  # noqa: N802
        self._forward("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._forward("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._forward("PUT")

    def do_DELETE(self) -> None:  # noqa: N802
        self._forward("DELETE")


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--upstream", default="https://opencode.ai/zen/go/v1")
    parser.add_argument("--session-key", default="honcho")
    parser.add_argument(
        "--proxy",
        default=None,
        help="Outbound HTTP proxy for the upstream (e.g. http://127.0.0.1:7897). "
        "Default: connect directly. Note http.client's built-in CONNECT tunnel uses "
        "HTTP/1.0, which some proxies (mihomo) reject — prefer a direct route when one works.",
    )
    args = parser.parse_args()

    parsed = urllib.parse.urlsplit(args.upstream)
    Handler.upstream_scheme = parsed.scheme or "https"
    Handler.upstream_host = parsed.hostname or "opencode.ai"
    Handler.upstream_port = parsed.port or (443 if Handler.upstream_scheme == "https" else 80)
    Handler.upstream_prefix = parsed.path.rstrip("/")
    Handler.session_key = args.session_key
    Handler.proxy = None if parsed.hostname in ("localhost", "127.0.0.1") else parse_proxy(args.proxy)

    server = Server((args.host, args.port), Handler)
    sys.stderr.write(
        "go-shim listening on http://%s:%d -> %s (session key=%s, proxy=%s)\n"
        % (args.host, args.port, args.upstream, args.session_key, Handler.proxy or "none")
    )
    sys.stderr.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
