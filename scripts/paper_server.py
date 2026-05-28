#!/usr/bin/env python3
"""
BTC Paper 合约机器人本地 Web 控制台。

仅提供本地 paper 模拟 API，不连接真实账户，不读取或保存任何 API Key。
"""

import argparse
import json
import mimetypes
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import paper_bot


ROOT_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT_DIR / "web"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
DEFAULT_AUTO_TICK_INTERVAL_SECONDS = 60
MIN_AUTO_TICK_INTERVAL_SECONDS = 5
MAX_AUTO_TICK_INTERVAL_SECONDS = 3600


def json_bytes(payload):
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def validate_auto_interval(value):
    try:
        interval = float(value)
    except (TypeError, ValueError) as exc:
        raise paper_bot.PaperBotError("auto tick interval must be numeric.") from exc
    if interval < MIN_AUTO_TICK_INTERVAL_SECONDS:
        raise paper_bot.PaperBotError(
            f"auto tick interval must be >= {MIN_AUTO_TICK_INTERVAL_SECONDS} seconds."
        )
    if interval > MAX_AUTO_TICK_INTERVAL_SECONDS:
        raise paper_bot.PaperBotError(
            f"auto tick interval must be <= {MAX_AUTO_TICK_INTERVAL_SECONDS} seconds."
        )
    return interval


class AutoTickController:
    """本地 paper 自动 tick 控制器，只调用模拟账本，不触达真实交易接口。"""

    def __init__(self, tick_func=None, default_interval=DEFAULT_AUTO_TICK_INTERVAL_SECONDS):
        self.tick_func = tick_func or paper_bot.command_tick
        self.interval_seconds = float(default_interval)
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread = None
        self.started_at = None
        self.stopped_at = None
        self.last_tick_at = None
        self.last_success_at = None
        self.last_error_at = None
        self.last_error = None
        self.last_result_status = None
        self.tick_count = 0
        self.error_count = 0

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def snapshot(self):
        with self._lock:
            return {
                "running": self.is_running(),
                "interval_seconds": self.interval_seconds,
                "started_at": self.started_at,
                "stopped_at": self.stopped_at,
                "last_tick_at": self.last_tick_at,
                "last_success_at": self.last_success_at,
                "last_error_at": self.last_error_at,
                "last_error": self.last_error,
                "last_result_status": self.last_result_status,
                "tick_count": self.tick_count,
                "error_count": self.error_count,
            }

    def start(self, interval_seconds=None):
        with self._lock:
            if self.is_running():
                snapshot = self.snapshot()
                snapshot["status"] = "already_running"
                return snapshot

            if interval_seconds is not None:
                self.interval_seconds = float(interval_seconds)
            self._stop_event.clear()
            self.started_at = paper_bot.utc_now()
            self.stopped_at = None
            self.last_error = None
            self._thread = threading.Thread(target=self._run_loop, name="paper-auto-tick", daemon=True)
            self._thread.start()
            snapshot = self.snapshot()
            snapshot["status"] = "started"
            return snapshot

    def stop(self):
        with self._lock:
            thread = self._thread
            if not thread or not thread.is_alive():
                self.stopped_at = self.stopped_at or paper_bot.utc_now()
                snapshot = self.snapshot()
                snapshot["status"] = "already_stopped"
                return snapshot
            self._stop_event.set()

        thread.join(timeout=2)
        with self._lock:
            if not thread.is_alive():
                self._thread = None
            self.stopped_at = paper_bot.utc_now()
            snapshot = self.snapshot()
            snapshot["status"] = "stopped"
            return snapshot

    def tick_once(self):
        tick_started_at = paper_bot.utc_now()
        try:
            payload = self.tick_func(SimpleNamespace(state_path=None))
        except Exception as exc:  # noqa: BLE001 - 自动循环必须记录错误并继续运行。
            with self._lock:
                self.last_tick_at = tick_started_at
                self.last_error_at = paper_bot.utc_now()
                self.last_error = str(exc)
                self.error_count += 1
                self.last_result_status = "error"
            return {"ok": False, "error": str(exc)}

        with self._lock:
            self.last_tick_at = tick_started_at
            self.last_success_at = paper_bot.utc_now()
            self.last_error = None
            self.tick_count += 1
            self.last_result_status = payload.get("status", "ok")
        return payload

    def _run_loop(self):
        while not self._stop_event.is_set():
            self.tick_once()
            self._stop_event.wait(self.interval_seconds)


AUTO_TICK = AutoTickController()


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
            self.send_json({
                "ok": True,
                "mode": "paper",
                "exchange": "mexc",
                "auto_tick": AUTO_TICK.snapshot()
            })
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
                status_payload = paper_bot.command_status(args)
                status_payload["auto_tick"] = AUTO_TICK.snapshot()
                self.send_json(status_payload)
                return
            if action == "auto/start":
                interval = validate_auto_interval(
                    payload.get("interval_seconds", DEFAULT_AUTO_TICK_INTERVAL_SECONDS)
                )
                self.send_json({"ok": True, "command": "auto/start", "auto_tick": AUTO_TICK.start(interval)})
                return
            if action == "auto/stop":
                self.send_json({"ok": True, "command": "auto/stop", "auto_tick": AUTO_TICK.stop()})
                return
            if action == "auto/status":
                self.send_json({"ok": True, "command": "auto/status", "auto_tick": AUTO_TICK.snapshot()})
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
        AUTO_TICK.stop()
        server.server_close()


if __name__ == "__main__":
    main()
