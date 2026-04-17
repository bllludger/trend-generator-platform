#!/usr/bin/env python3
"""
Face-ID autocrop probe:
1) Copies input image into shared storage root.
2) Sends POST /v1/process to face-id-api.
3) Runs a local callback server and waits for result.
4) Saves original + selected (cropped/fallback) into output dir.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import shutil
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error, request


def _build_signature(secret: str, timestamp: str, body: bytes) -> str:
    payload = timestamp.encode("utf-8") + body
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


@dataclass
class CallbackState:
    event: threading.Event
    payload: dict | None = None
    raw_body: bytes | None = None
    signature_ok: bool = False
    error: str | None = None


def _make_handler(state: CallbackState, callback_secret: str):
    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            if self.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return

            content_len = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(content_len)
            ts = (self.headers.get("X-FaceId-Timestamp") or "").strip()
            sig = (self.headers.get("X-FaceId-Signature") or "").strip()

            if not ts or not sig:
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b"missing signature headers")
                state.error = "missing signature headers"
                return

            expected = _build_signature(callback_secret, ts, body)
            if not hmac.compare_digest(expected, sig):
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b"bad signature")
                state.error = "bad signature"
                return

            try:
                payload = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"invalid json")
                state.error = "invalid json"
                return

            state.raw_body = body
            state.payload = payload
            state.signature_ok = True
            state.event.set()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, fmt: str, *args):  # noqa: A003
            # keep console output clean
            return

    return _Handler


def _post_json(url: str, payload: dict, timeout: float) -> tuple[int, dict | str]:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url=url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            code = int(resp.status)
            try:
                return code, json.loads(body)
            except Exception:
                return code, body
    except error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return int(e.code), json.loads(body)
        except Exception:
            return int(e.code), body


def _copy_if_exists(src: str | None, dst: Path) -> bool:
    if not src:
        return False
    p = Path(src)
    if not p.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, dst)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Send photo to Face-ID API and save crop result.")
    parser.add_argument("--image", required=True, help="Path to input photo.")
    parser.add_argument("--api-url", default="http://127.0.0.1:8010", help="Face-ID API base URL.")
    parser.add_argument(
        "--storage-root",
        default="./data/generated_images",
        help="Shared storage root mounted to /data/generated_images in docker-compose.",
    )
    parser.add_argument(
        "--container-storage-root",
        default="/data/generated_images",
        help="Storage root as seen from face-id containers.",
    )
    parser.add_argument(
        "--output-dir",
        default="./reports/face_id_probe",
        help="Directory where output files will be stored.",
    )
    parser.add_argument("--user-id", default="probe-user")
    parser.add_argument("--chat-id", default="0")
    parser.add_argument("--flow", default="trend")
    parser.add_argument("--callback-bind", default="0.0.0.0")
    parser.add_argument(
        "--callback-host",
        default="host.docker.internal",
        help="Host that face-id-worker can reach (for callback URL).",
    )
    parser.add_argument("--callback-port", type=int, default=8787)
    parser.add_argument("--callback-secret", default="face-id-dev-secret")
    parser.add_argument("--callback-secret-id", default="v1")
    parser.add_argument("--timeout", type=int, default=60, help="Wait callback timeout in seconds.")
    args = parser.parse_args()

    image_path = Path(args.image).expanduser().resolve()
    if not image_path.exists():
        print(f"Input image not found: {image_path}", file=sys.stderr)
        return 1

    asset_id = str(uuid.uuid4())
    request_id = str(uuid.uuid4())
    storage_root = Path(args.storage_root).expanduser().resolve()
    source_dir = storage_root / "face_id_probe" / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    staged_source = source_dir / f"{asset_id}{image_path.suffix.lower() or '.jpg'}"
    shutil.copy2(image_path, staged_source)

    out_dir = Path(args.output_dir).expanduser().resolve() / asset_id
    out_dir.mkdir(parents=True, exist_ok=True)

    callback_state = CallbackState(event=threading.Event())
    handler_cls = _make_handler(callback_state, args.callback_secret)
    server = ThreadingHTTPServer((args.callback_bind, args.callback_port), handler_cls)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    callback_url = f"http://{args.callback_host}:{args.callback_port}/callback"
    try:
        rel_inside_storage = staged_source.relative_to(storage_root)
    except ValueError:
        print(f"Staged source is not under storage-root: {staged_source} not in {storage_root}", file=sys.stderr)
        return 1
    container_source_path = str(Path(args.container_storage_root) / rel_inside_storage)

    payload = {
        "asset_id": asset_id,
        "source_path": container_source_path,
        "flow": args.flow,
        "user_id": args.user_id,
        "chat_id": args.chat_id,
        "request_id": request_id,
        "callback_url": callback_url,
        "callback_secret_id": args.callback_secret_id,
        "detector_config": {},
    }

    try:
        process_url = args.api_url.rstrip("/") + "/v1/process"
        code, body = _post_json(process_url, payload, timeout=10.0)
        if code != 202:
            print(f"Face-ID API returned {code}: {body}", file=sys.stderr)
            return 2

        print(f"Queued asset_id={asset_id}")
        print(f"Waiting callback on {callback_url} (timeout={args.timeout}s)...")
        ok = callback_state.event.wait(timeout=args.timeout)
        if not ok:
            print("Callback timeout: no result received.", file=sys.stderr)
            return 3

        result = callback_state.payload or {}
        status = str(result.get("status") or "")
        selected_path = result.get("selected_path")
        source_path = result.get("source_path") or str(staged_source)

        raw_json_path = out_dir / "callback_payload.json"
        raw_json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

        source_saved = _copy_if_exists(source_path, out_dir / "source_original" / Path(str(source_path)).name)
        selected_saved = _copy_if_exists(selected_path, out_dir / "selected_result" / Path(str(selected_path)).name)

        # Convenience fallback for "ready" with expected path but missing callback selected_path.
        if not selected_saved and status == "ready":
            expected = storage_root / "face_id" / f"{asset_id}.jpg"
            selected_saved = _copy_if_exists(str(expected), out_dir / "selected_result" / expected.name)

        summary = {
            "asset_id": asset_id,
            "status": status,
            "faces_detected": result.get("faces_detected"),
            "signature_ok": callback_state.signature_ok,
            "staged_source_host": str(staged_source),
            "source_path_sent_to_api": container_source_path,
            "source_saved": bool(source_saved),
            "selected_saved": bool(selected_saved),
            "selected_path": selected_path,
            "source_path": source_path,
            "detector_meta": result.get("detector_meta") or {},
            "output_dir": str(out_dir),
        }
        (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    finally:
        server.shutdown()
        server.server_close()
        # let socket close cleanly before process exit
        time.sleep(0.1)


if __name__ == "__main__":
    raise SystemExit(main())
