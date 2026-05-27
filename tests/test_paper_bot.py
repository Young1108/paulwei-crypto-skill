import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "paper_bot.py"
SPEC = importlib.util.spec_from_file_location("paper_bot", SCRIPT)
paper_bot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(paper_bot)


FIXTURE_ANALYSIS = {
    "symbol": "BTCUSDT",
    "data_source": {"provider": "mexc", "instrument": "BTC_USDT"},
    "timestamp": "2026-05-23 00:00 UTC",
    "price": {"current": 76000.0, "change_pct_24h": -2.0},
    "ma": {"ma7": 77000.0, "ma14": 78000.0, "ma30": 78500.0, "ma30_dev_pct": -3.2},
    "range_30d": {"high": 82800.0, "low": 74900.0},
    "levels": {"resistance": [78000.0, 79000.0], "support": [74900.0, 73670.0]},
    "structure_4h": {
        "trend": "下降趋势",
        "key_zones": [{"low": 76800.0, "high": 77600.0, "touches": 10}]
    },
    "weekly": {"trend": "上升"},
    "funding": {"avg_8period_pct": 0.001},
}


class PaperBotUnitTest(unittest.TestCase):
    def test_symbol_validation_rejects_query_pollution(self):
        with self.assertRaises(paper_bot.PaperBotError):
            paper_bot.normalize_symbol("BTCUSDT&limit=1")

    def test_standard_risk_for_500_account(self):
        state = paper_bot.initial_state(500)
        risk_amount = state["equity"] * paper_bot.STANDARD_RISK_PCT
        self.assertEqual(risk_amount, 2.5)

    def test_mexc_contract_rounding(self):
        contracts = paper_bot.contracts_from_notional(200, 75000)
        self.assertEqual(contracts, 26)

    def test_leverage_above_three_is_rejected(self):
        with self.assertRaises(paper_bot.PaperBotError):
            paper_bot.validate_leverage(3.1)

    def test_daily_loss_lock(self):
        state = paper_bot.initial_state(500)
        state["closed_trades"].append({
            "closed_at": paper_bot.today_utc() + "T00:00:00Z",
            "realized_pnl": -10.01,
        })
        locked, daily_pnl, lock_amount = paper_bot.is_risk_locked(state)
        self.assertTrue(locked)
        self.assertLessEqual(daily_pnl, lock_amount)

    def test_placeable_short_plan_uses_risk_cap(self):
        state = paper_bot.initial_state(500)
        result = paper_bot.build_short_plan(
            state,
            FIXTURE_ANALYSIS,
            paper_bot.STANDARD_RISK_PCT,
            3.0,
        )
        self.assertEqual(result["status"], "placeable")
        self.assertLessEqual(result["plan"]["max_loss_usdt"], 2.5)
        self.assertLessEqual(result["plan"]["leverage"], 3.0)
        self.assertEqual(result["plan"]["total_contracts"], sum(e["contracts"] for e in result["plan"]["entries"]))

    def test_cancel_all_marks_pending_plan_and_open_order(self):
        state = paper_bot.initial_state(500)
        state["pending_plans"].append({"plan_id": "plan_test", "status": "pending"})
        state["open_orders"].append({
            "order_id": "po_test",
            "plan_id": "plan_test",
            "status": "open",
            "reduce_only": False,
        })
        result = paper_bot.cancel_items(state, cancel_all=True)
        self.assertEqual(result["cancelled_count"], 2)
        self.assertEqual(state["pending_plans"][0]["status"], "cancelled")
        self.assertEqual(state["open_orders"][0]["status"], "cancelled")

    def test_entry_order_does_not_fill_on_creation_candle(self):
        state = paper_bot.initial_state(500)
        order = {
            "order_id": "po_test",
            "plan_id": "plan_test",
            "symbol": "BTCUSDT",
            "instrument": "BTC_USDT",
            "side": "short",
            "price": 100.0,
            "contracts": 10,
            "stop_loss": 105.0,
            "take_profits": [],
            "leverage": 3.0,
            "created_candle_time": 1000,
        }
        same_candle = {"time": 1000, "high": 101.0, "low": 99.0}
        next_candle = {"time": 61000, "high": 101.0, "low": 99.0}
        self.assertIsNone(paper_bot.fill_entry_order(state, order, same_candle))
        self.assertIsNotNone(paper_bot.fill_entry_order(state, order, next_candle))
        self.assertEqual(order["status"], "filled")

    def test_expired_pending_plan_is_not_active(self):
        state = paper_bot.initial_state(500)
        state["pending_plans"].append({
            "plan_id": "plan_old",
            "status": "pending",
            "expires_at": "2020-01-01T00:00:00Z",
        })
        expired = paper_bot.expire_stale_items(state)
        self.assertEqual(expired[0]["type"], "plan")
        self.assertEqual(state["pending_plans"][0]["status"], "expired")
        self.assertEqual(paper_bot.active_pending_plans(state), [])

    def test_legacy_open_order_expires_from_created_at(self):
        state = paper_bot.initial_state(500)
        state["open_orders"].append({
            "order_id": "po_old",
            "plan_id": "plan_old",
            "status": "open",
            "reduce_only": False,
            "created_at": "2020-01-01T00:00:00Z",
        })
        expired = paper_bot.expire_stale_items(state)
        self.assertEqual(expired[0]["type"], "order")
        self.assertEqual(state["open_orders"][0]["status"], "expired")


class PaperBotCliTest(unittest.TestCase):
    def test_init_propose_place_tick_status_flow_with_fixtures(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            state_path = tmp / "paper_state.json"
            analysis_path = tmp / "analysis.json"
            market_path = tmp / "market.json"
            analysis_path.write_text(json.dumps(FIXTURE_ANALYSIS), encoding="utf-8")
            market_path.write_text(json.dumps({
                "candle": {
                    "time": 1779479520000,
                    "open": 76000.0,
                    "high": 77250.0,
                    "low": 75500.0,
                    "close": 77150.0,
                    "volume": 1000.0,
                },
                "ticker": {
                    "price": 77150.0,
                    "fair_price": 77150.0,
                    "funding_rate": 0.00001,
                    "timestamp": 1779479520000,
                }
            }), encoding="utf-8")
            env = os.environ.copy()
            env["PAPER_BOT_ANALYSIS_FIXTURE"] = str(analysis_path)
            env["PAPER_BOT_MARKET_FIXTURE"] = str(market_path)

            init = self.run_cli(["init", "--balance", "500", "--state-path", str(state_path)], env)
            self.assertTrue(init["ok"])
            proposal = self.run_cli([
                "propose", "--symbol", "BTCUSDT", "--side", "short",
                "--state-path", str(state_path)
            ], env)
            self.assertEqual(proposal["status"], "placeable")
            plan_id = proposal["plan"]["plan_id"]
            placed = self.run_cli(["place", "--plan-id", plan_id, "--state-path", str(state_path)], env)
            self.assertTrue(placed["ok"])
            tick = self.run_cli(["tick", "--state-path", str(state_path)], env)
            self.assertTrue(tick["ok"])
            status = self.run_cli(["status", "--no-market", "--state-path", str(state_path)], env)
            self.assertTrue(status["ok"])

    def test_tick_skips_duplicate_candle_without_closing_position(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            state_path = tmp / "paper_state.json"
            market_path = tmp / "market.json"
            candle_time = 1779479520000
            state = paper_bot.initial_state(500)
            state["last_processed_candle_time"] = candle_time
            state["positions"].append({
                "position_id": "pos_test",
                "plan_id": "plan_test",
                "opened_at": paper_bot.utc_now(),
                "symbol": "BTCUSDT",
                "instrument": "BTC_USDT",
                "side": "short",
                "entry_price": 100.0,
                "original_contracts": 10,
                "remaining_contracts": 10,
                "stop_loss": 105.0,
                "take_profits": [],
                "leverage": 3.0,
                "fees_paid": 0.0,
                "realized_pnl": 0.0,
            })
            state_path.write_text(json.dumps(state), encoding="utf-8")
            market_path.write_text(json.dumps({
                "candle": {
                    "time": candle_time,
                    "open": 100.0,
                    "high": 110.0,
                    "low": 95.0,
                    "close": 100.0,
                    "volume": 1000.0,
                },
                "ticker": {
                    "price": 100.0,
                    "fair_price": 100.0,
                    "funding_rate": 0.00001,
                    "timestamp": candle_time,
                }
            }), encoding="utf-8")
            env = os.environ.copy()
            env["PAPER_BOT_MARKET_FIXTURE"] = str(market_path)
            tick = self.run_cli(["tick", "--state-path", str(state_path)], env)
            self.assertEqual(tick["status"], "already_processed")
            stored = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["positions"][0]["remaining_contracts"], 10)
            self.assertEqual(stored["closed_trades"], [])

    def run_cli(self, args, env):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT)] + args,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        return json.loads(completed.stdout)


if __name__ == "__main__":
    unittest.main()
