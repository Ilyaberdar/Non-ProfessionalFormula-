#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer


WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "0.0.0.0")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "9000"))
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/github-webhook")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
DEPLOY_BRANCH = os.getenv("DEPLOY_BRANCH", "main")
DEPLOY_SCRIPT = os.getenv("DEPLOY_SCRIPT", "/opt/non-professional-formula/deploy/deploy.sh")


def verify_signature(secret: str, payload: bytes, signature_header: str) -> bool:
    if not secret or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path != WEBHOOK_PATH:
            self.send_error(HTTPStatus.NOT_FOUND, "not found")
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(content_length)
        signature = self.headers.get("X-Hub-Signature-256", "")
        event = self.headers.get("X-GitHub-Event", "")

        if event == "ping":
            self._send_json(HTTPStatus.OK, {"ok": True, "message": "pong"})
            return

        if event != "push":
            self._send_json(HTTPStatus.ACCEPTED, {"ok": True, "message": f"ignored event {event}"})
            return

        if not verify_signature(WEBHOOK_SECRET, payload, signature):
            self._send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "message": "invalid signature"})
            return

        try:
            body = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "message": "invalid json"})
            return

        pushed_ref = body.get("ref", "")
        expected_ref = f"refs/heads/{DEPLOY_BRANCH}"
        if pushed_ref != expected_ref:
            self._send_json(
                HTTPStatus.ACCEPTED,
                {"ok": True, "message": f"ignored ref {pushed_ref or 'unknown'}"},
            )
            return

        subprocess.Popen(
            [DEPLOY_SCRIPT],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self._send_json(HTTPStatus.ACCEPTED, {"ok": True, "message": "deploy started"})

    def log_message(self, format: str, *args) -> None:
        return

    def _send_json(self, status: HTTPStatus, payload: dict) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


if __name__ == "__main__":
    if not WEBHOOK_SECRET:
        raise RuntimeError("WEBHOOK_SECRET is required")
    server = ThreadingHTTPServer((WEBHOOK_HOST, WEBHOOK_PORT), WebhookHandler)
    print(f"listening on {WEBHOOK_HOST}:{WEBHOOK_PORT}{WEBHOOK_PATH}")
    server.serve_forever()
