#!/usr/bin/env python3
"""
BTC Paper 合约机器人本地 Web 控制台。

仅提供本地 paper 模拟 API，不连接真实账户，不读取或保存任何 API Key。
"""

import argparse
import json
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import paper_bot


ROOT_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT_DIR / "web"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787


def json_bytes(payload):
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


class PaperRequestHandler(BaseHTTPRequestHandler):
    server_version = "PaperBotHTTP/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[paper-server] " + fmt % args + "\n")

    def send_json(self, payload, status=200):
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:%s" % self.server.server_port)
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def send_static(self, path):
        if path == "/":
            path = "/index.html"
        relative = path.lstrip("/")
        file_path = (WEB_DIR / relative).resolve()
        if not str(file_path).startswith(str(WEB_DIR.resolve())) or not file_path.exists():
            self.send_json({"ok": False, "error": "not found"}, status=404)
            return
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw_body = self.rfile.read(length).decode("utf-8")
        try:
            return json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise paper_bot.PaperBotError("invalid JSON body") from exc

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:%s" % self.server.server_port)
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            self.handle_api("status", {})
            return
        if parsed.path == "/api/health":
            self.send_json({"ok": True, "mode": "paper", "exchange": "mexc"})
            return
        self.send_static(parsed.path)

    def do_POST(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            self.send_json({"ok": False, "error": "not found"}, status=404)
            return
        try:
            payload = self.read_json_body()
            self.handle_api(parsed.path.removeprefix("/api/"), payload)
        except paper_bot.PaperBotError as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:  # noqa: BLE001 - HTTP 边界统一转 JSON。
            self.send_json({"ok": False, "error": f"internal error: {exc}"}, status=500)

    def handle_api(self, action, payload):
        try:
            if action == "init":
                args = SimpleNamespace(
                    balance=float(payload.get("balance", paper_bot.DEFAULT_BALANCE)),
                    state_path=None,
                )
                self.send_json(paper_bot.command_init(args))
                return
            if action == "propose":
                args = SimpleNamespace(
                    symbol=str(payload.get("symbol", "BTCUSDT")),
                    side=str(payload.get("side", "short")),
                    risk_pct=float(payload.get("risk_pct", paper_bot.STANDARD_RISK_PCT)),
                    leverage=float(payload.get("leverage", paper_bot.MAX_LEVERAGE)),
                    state_path=None,
                )
                self.send_json(paper_bot.command_propose(args))
                return
            if action == "place":
                plan_id = str(payload.get("plan_id", "")).strip()
                if not plan_id:
                    raise paper_bot.PaperBotError("plan_id is required")
                args = SimpleNamespace(plan_id=plan_id, state_path=None)
                self.send_json(paper_bot.command_place(args))
                return
            if action == "cancel":
                args = SimpleNamespace(
                    all=bool(payload.get("all", False)),
                    plan_id=str(payload.get("plan_id", "")).strip() or None,
                    order_id=str(payload.get("order_id", "")).strip() or None,
                    state_path=None,
                )
                self.send_json(paper_bot.command_cancel(args))
                return
            if action == "tick":
                args = SimpleNamespace(state_path=None)
                self.send_json(paper_bot.command_tick(args))
                return
            if action == "status":
                args = SimpleNamespace(state_path=None, no_market=bool(payload.get("no_market", False)))
                self.send_json(paper_bot.command_status(args))
                return
            self.send_json({"ok": False, "error": "unknown API action"}, status=404)
        except paper_bot.PaperBotError as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=400)


def main():
    parser = argparse.ArgumentParser(description="Run local BTC paper bot web UI.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    if not WEB_DIR.exists():
        raise SystemExit(f"web directory not found: {WEB_DIR}")

    server = ThreadingHTTPServer((args.host, args.port), PaperRequestHandler)
    print(f"Paper bot UI: http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping paper bot UI.", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
