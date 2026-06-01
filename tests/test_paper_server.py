import importlib.util
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

SCRIPT = ROOT / "scripts" / "paper_server.py"
SPEC = importlib.util.spec_from_file_location("paper_server", SCRIPT)
paper_server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(paper_server)


class AutoTickControllerTest(unittest.TestCase):
    def test_auto_tick_controller_runs_and_stops(self):
        event = threading.Event()

        def fake_tick(_args):
            event.set()
            return {"ok": True, "status": "processed"}

        controller = paper_server.AutoTickController(tick_func=fake_tick, default_interval=0.01)
        started = controller.start(interval_seconds=0.01)
        try:
            self.assertEqual(started["status"], "started")
            self.assertTrue(event.wait(1.0))
            snapshot = controller.snapshot()
            deadline = time.time() + 1.0
            while snapshot["tick_count"] < 1 and time.time() < deadline:
                time.sleep(0.01)
                snapshot = controller.snapshot()
            self.assertTrue(snapshot["running"])
            self.assertGreaterEqual(snapshot["tick_count"], 1)
            self.assertIsNone(snapshot["last_error"])
            self.assertEqual(snapshot["last_result_status"], "processed")
        finally:
            stopped = controller.stop()
        self.assertEqual(stopped["status"], "stopped")
        self.assertFalse(controller.snapshot()["running"])

    def test_auto_tick_controller_records_errors_without_crashing(self):
        def bad_tick(_args):
            raise RuntimeError("fixture failure")

        controller = paper_server.AutoTickController(tick_func=bad_tick, default_interval=0.01)
        result = controller.tick_once()
        snapshot = controller.snapshot()
        self.assertFalse(result["ok"])
        self.assertEqual(snapshot["error_count"], 1)
        self.assertEqual(snapshot["last_result_status"], "error")
        self.assertIn("fixture failure", snapshot["last_error"])

    def test_auto_tick_controller_halts_after_consecutive_errors(self):
        def bad_tick(_args):
            raise RuntimeError("fixture failure")

        controller = paper_server.AutoTickController(tick_func=bad_tick, default_interval=0.01)
        result = None
        for _ in range(paper_server.MAX_AUTO_CONSECUTIVE_ERRORS):
            result = controller.tick_once()
        snapshot = controller.snapshot()

        self.assertFalse(result["ok"])
        self.assertEqual(snapshot["consecutive_error_count"], paper_server.MAX_AUTO_CONSECUTIVE_ERRORS)
        self.assertEqual(snapshot["last_result_status"], "halted_error")
        self.assertIsNotNone(snapshot["halted_at"])
        self.assertIn("连续", snapshot["halt_reason"])

    def test_auto_tick_controller_success_resets_consecutive_errors(self):
        def bad_tick(_args):
            raise RuntimeError("fixture failure")

        controller = paper_server.AutoTickController(tick_func=bad_tick, default_interval=0.01)
        controller.tick_once()
        controller.tick_func = lambda _args: {"ok": True, "status": "processed"}
        result = controller.tick_once()
        snapshot = controller.snapshot()

        self.assertTrue(result["ok"])
        self.assertEqual(snapshot["consecutive_error_count"], 0)
        self.assertEqual(snapshot["last_result_status"], "processed")

    def test_auto_tick_controller_passes_configured_state_path(self):
        seen = {}

        def fake_tick(args):
            seen["state_path"] = args.state_path
            return {"ok": True, "status": "processed"}

        expected_path = str(Path("/tmp/paper_state_fixture.json").expanduser().resolve())
        controller = paper_server.AutoTickController(tick_func=fake_tick, default_interval=60)
        controller.set_state_path(expected_path)
        result = controller.tick_once()
        snapshot = controller.snapshot()
        self.assertTrue(result["ok"])
        self.assertEqual(seen["state_path"], expected_path)
        self.assertEqual(snapshot["state_path"], expected_path)

    def test_auto_tick_controller_scan_mode_calls_scan_func(self):
        seen = {}

        def fake_scan(args):
            seen["state_path"] = args.state_path
            seen["risk_pct"] = args.risk_pct
            seen["leverage"] = args.leverage
            return {"ok": True, "command": "scan", "proposal": {"status": "placeable"}}

        controller = paper_server.AutoTickController(
            tick_func=lambda _args: {"ok": True, "status": "processed"},
            scan_func=fake_scan,
            default_interval=60,
        )
        controller.set_state_path("/private/tmp/scan_mode_state.json")
        controller.start(
            interval_seconds=60,
            mode="scan",
            scan_symbol="BTCUSDT",
            scan_side="short",
            scan_risk_pct=0.0025,
            scan_leverage=2,
            max_consecutive_errors=5,
        )
        try:
            result = controller.tick_once()
        finally:
            controller.stop()
        snapshot = controller.snapshot()
        self.assertEqual(result["command"], "scan")
        self.assertEqual(seen["state_path"], "/private/tmp/scan_mode_state.json")
        self.assertEqual(seen["risk_pct"], 0.0025)
        self.assertEqual(seen["leverage"], 2.0)
        self.assertEqual(snapshot["mode"], "scan")
        self.assertEqual(snapshot["last_result_status"], "placeable")
        self.assertEqual(snapshot["max_consecutive_errors"], 5)

    def test_api_interval_validation(self):
        with self.assertRaises(paper_server.paper_bot.PaperBotError):
            paper_server.validate_auto_interval(1)
        self.assertEqual(paper_server.validate_auto_interval(60), 60.0)

    def test_auto_mode_validation(self):
        self.assertEqual(paper_server.validate_auto_mode("scan"), "scan")
        with self.assertRaises(paper_server.paper_bot.PaperBotError):
            paper_server.validate_auto_mode("place")

    def test_auto_max_consecutive_errors_validation(self):
        self.assertEqual(paper_server.validate_auto_max_consecutive_errors(3), 3)
        with self.assertRaises(paper_server.paper_bot.PaperBotError):
            paper_server.validate_auto_max_consecutive_errors(0)
        with self.assertRaises(paper_server.paper_bot.PaperBotError):
            paper_server.validate_auto_max_consecutive_errors(11)

    def test_run_paper_command_uses_state_lock(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "paper_state.json"
            seen = {}

            def fake_command(args):
                lock_path = paper_server.paper_bot.state_lock_path(Path(args.state_path))
                seen["lock_exists"] = lock_path.exists()
                return {"ok": True}

            result = paper_server.run_paper_command(
                fake_command,
                paper_server.SimpleNamespace(state_path=str(state_path)),
            )

            self.assertTrue(result["ok"])
            self.assertTrue(seen["lock_exists"])

    def test_export_state_payload_contains_paper_only_ledger(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "paper_state.json"
            state = paper_server.paper_bot.initial_state(500)
            paper_server.paper_bot.save_state(state_path, state)
            payload = paper_server.export_state_payload(state_path)
            serialized = paper_server.json.dumps(payload, ensure_ascii=False).lower()

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["paper_only"])
        self.assertEqual(payload["command"], "export/state")
        self.assertEqual(payload["ledger"]["cash_balance"], 500.0)
        self.assertNotIn("api_key", serialized)
        self.assertNotIn("private_key", serialized)
        self.assertNotIn("mnemonic", serialized)

    def test_export_state_payload_requires_initialized_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "missing_state.json"
            with self.assertRaises(paper_server.paper_bot.PaperBotError):
                paper_server.export_state_payload(state_path)

    def test_backup_index_payload_lists_existing_backups(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "paper_state.json"
            backup_dir = Path(tmpdir) / "backups"
            backup_dir.mkdir()
            backup_path = backup_dir / "paper_state.20260101_000000.aaaaaaaa.json"
            backup_path.write_text("{}", encoding="utf-8")

            payload = paper_server.backup_index_payload(state_path)

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["command"], "backups")
            self.assertEqual(payload["backups"][0]["name"], backup_path.name)
            self.assertEqual(Path(payload["backup_dir"]), backup_dir.resolve())


if __name__ == "__main__":
    unittest.main()
