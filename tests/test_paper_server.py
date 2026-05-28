import importlib.util
import sys
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

    def test_api_interval_validation(self):
        with self.assertRaises(paper_server.paper_bot.PaperBotError):
            paper_server.validate_auto_interval(1)
        self.assertEqual(paper_server.validate_auto_interval(60), 60.0)


if __name__ == "__main__":
    unittest.main()
