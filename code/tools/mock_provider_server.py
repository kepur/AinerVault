from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    server_version = "MockProvider/1.0"

    def _write_json(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in {"/", "/health", "/healthz"}:
            self._write_json(200, {"ok": True, "service": "mock-provider", "path": self.path})
            return
        self._write_json(404, {"ok": False, "detail": f"unknown path: {self.path}"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            payload = {"raw": raw.decode("utf-8", errors="replace")}

        if self.path == "/v1/chat/completions":
            message = {
                "role": "assistant",
                "content": json.dumps({"status": "ok", "echo": payload.get("messages", [])[-1] if payload.get("messages") else None}),
            }
            self._write_json(
                200,
                {
                    "id": "chatcmpl_mock_001",
                    "object": "chat.completion",
                    "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 18, "total_tokens": 30},
                },
            )
            return

        if self.path in {"/v1/videos/generations", "/v1/video/generations", "/v1/video/generate", "/generate"}:
            self._write_json(
                200,
                {
                    "task_id": "vid_mock_001",
                    "video_url": "http://mock.local/video.mp4",
                    "duration_ms": int(payload.get("duration_ms") or 4000),
                    "fps": int(payload.get("fps") or 12),
                    "echo": payload,
                },
            )
            return

        if self.path in {"/v1/audio/generations", "/v1/audio/generate", "/v1/music/generations", "/v1/sound-effects/generations"}:
            self._write_json(
                200,
                {
                    "task_id": "aud_mock_001",
                    "audio_url": "http://mock.local/audio.mp3",
                    "duration_ms": int(payload.get("duration_ms") or 8000),
                    "echo": payload,
                },
            )
            return

        if self.path == "/v1/audio/speech":
            self._write_json(
                200,
                {
                    "audio_url": "http://mock.local/speech.mp3",
                    "duration_ms": 3200,
                    "voice": payload.get("voice", "alloy"),
                    "format": payload.get("format", "mp3"),
                },
            )
            return

        if self.path == "/v1/images/generations":
            self._write_json(
                200,
                {
                    "data": [{"url": "http://mock.local/image.png"}],
                    "width": 1024,
                    "height": 1024,
                    "echo": payload,
                },
            )
            return

        self._write_json(404, {"ok": False, "detail": f"unknown path: {self.path}", "echo": payload})

    def log_message(self, format: str, *args):
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 18080), Handler)
    print("mock provider listening on 0.0.0.0:18080", flush=True)
    server.serve_forever()
