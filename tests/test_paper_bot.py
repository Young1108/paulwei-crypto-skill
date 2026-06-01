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

WAIT_ANALYSIS = json.loads(json.dumps(FIXTURE_ANALYSIS))
WAIT_ANALYSIS["structure_4h"]["trend"] = "震荡"
WAIT_ANALYSIS["ma"]["ma7"] = 75000.0
WAIT_ANALYSIS["ma"]["ma14"] = 74000.0
WAIT_ANALYSIS["levels"]["support"] = [73000.0, 72000.0]


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

    def test_performance_summary_tracks_win_rate_and_profit_factor(self):
        state = paper_bot.initial_state(500)
        state["closed_trades"].extend([
            {"realized_pnl": 3.0, "closed_at": paper_bot.utc_now()},
            {"realized_pnl": -1.0, "closed_at": paper_bot.utc_now()},
            {"realized_pnl": 2.0, "closed_at": paper_bot.utc_now()},
        ])
        summary = paper_bot.performance_summary(state, unrealized=0.5)
        self.assertEqual(summary["trade_count"], 3)
        self.assertEqual(summary["wins"], 2)
        self.assertEqual(summary["losses"], 1)
        self.assertEqual(summary["win_rate_pct"], 66.67)
        self.assertEqual(summary["profit_factor"], 5.0)
        self.assertEqual(summary["net_pnl_usdt"], 4.5)

    def test_risk_summary_reports_daily_remaining_and_risk_caps(self):
        state = paper_bot.initial_state(500)
        state["closed_trades"].append({
            "closed_at": paper_bot.today_utc() + "T00:00:00Z",
            "realized_pnl": -3.0,
        })
        summary = paper_bot.risk_summary(state)
        self.assertEqual(summary["standard_risk_usdt"], 2.5)
        self.assertEqual(summary["max_risk_usdt"], 5.0)
        self.assertEqual(summary["daily_loss_limit_usdt"], 10.0)
        self.assertEqual(summary["daily_loss_used_usdt"], 3.0)
        self.assertEqual(summary["daily_loss_remaining_usdt"], 7.0)
        self.assertFalse(summary["risk_locked"])
        self.assertEqual(summary["max_leverage"], 3.0)

    def test_pause_and_resume_update_manual_control_state(self):
        state = paper_bot.initial_state(500)
        pause_event = paper_bot.pause_trading(state, "test_pause")
        self.assertTrue(state["trading_paused"])
        self.assertEqual(state["pause_reason"], "test_pause")
        self.assertEqual(pause_event["event_type"], "manual_pause")
        resume_event = paper_bot.resume_trading(state, "test_resume")
        self.assertFalse(state["trading_paused"])
        self.assertIsNone(state["pause_reason"])
        self.assertEqual(resume_event["event_type"], "manual_resume")

    def test_proposal_control_reports_cooldown_blocker(self):
        state = paper_bot.initial_state(500)
        state["last_proposal_at"] = paper_bot.utc_now()
        state["last_proposal_status"] = "wait"
        summary = paper_bot.proposal_control_summary(state)
        self.assertFalse(summary["can_propose"])
        self.assertIn("cooldown", summary["blockers"])
        self.assertGreater(summary["cooldown_remaining_seconds"], 0)

    def test_proposal_cooldown_validation_rejects_out_of_range(self):
        with self.assertRaises(paper_bot.PaperBotError):
            paper_bot.validate_proposal_cooldown_seconds(59)
        with self.assertRaises(paper_bot.PaperBotError):
            paper_bot.validate_proposal_cooldown_seconds(3601)
        self.assertEqual(paper_bot.validate_proposal_cooldown_seconds(120), 120)

    def test_state_file_lock_creates_sidecar_lock_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "paper_state.json"
            lock_path = paper_bot.state_lock_path(state_path)
            with paper_bot.state_file_lock(state_path) as active_lock:
                self.assertEqual(active_lock, lock_path)
                self.assertTrue(lock_path.exists())


class PaperBotCliTest(unittest.TestCase):
    def test_init_backs_up_existing_state_before_reset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "paper_state.json"
            env = os.environ.copy()
            first = self.run_cli(["init", "--balance", "500", "--state-path", str(state_path)], env)
            self.assertIsNone(first["backup_path"])
            second = self.run_cli(["init", "--balance", "600", "--state-path", str(state_path)], env)
            backup_path = Path(second["backup_path"])
            self.assertTrue(backup_path.exists())
            backup_state = json.loads(backup_path.read_text(encoding="utf-8"))
            current_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(backup_state["initial_balance"], 500.0)
            self.assertEqual(current_state["initial_balance"], 600.0)
            self.assertTrue(paper_bot.state_lock_path(state_path).exists())

    def test_backup_pruning_keeps_recent_state_backups(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "paper_state.json"
            backup_dir = Path(tmpdir) / "backups"
            backup_dir.mkdir()
            for index in range(22):
                backup_path = backup_dir / f"paper_state.20260101_0000{index:02d}.{index:08d}.json"
                backup_path.write_text(json.dumps({"index": index}), encoding="utf-8")
                os.utime(backup_path, (index, index))

            removed = paper_bot.prune_state_backups(state_path, keep=20)
            remaining = paper_bot.state_backup_files(state_path)
            remaining_names = {path.name for path in remaining}

            self.assertEqual(len(removed), 2)
            self.assertEqual(len(remaining), 20)
            self.assertNotIn("paper_state.20260101_000000.00000000.json", remaining_names)
            self.assertNotIn("paper_state.20260101_000001.00000001.json", remaining_names)
            self.assertIn("paper_state.20260101_000021.00000021.json", remaining_names)

    def test_backups_command_lists_metadata_newest_first(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "paper_state.json"
            backup_dir = Path(tmpdir) / "backups"
            backup_dir.mkdir()
            first_backup = backup_dir / "paper_state.20260101_000000.aaaaaaaa.json"
            second_backup = backup_dir / "paper_state.20260101_000100.bbbbbbbb.json"
            first_backup.write_text(json.dumps({"initial_balance": 500}), encoding="utf-8")
            second_backup.write_text(json.dumps({"initial_balance": 600}), encoding="utf-8")
            os.utime(first_backup, (100, 100))
            os.utime(second_backup, (200, 200))

            payload = self.run_cli(["backups", "--state-path", str(state_path)], os.environ.copy())

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["command"], "backups")
            self.assertEqual(payload["retention_count"], paper_bot.BACKUP_RETENTION_COUNT)
            self.assertEqual([item["name"] for item in payload["backups"]], [
                second_backup.name,
                first_backup.name,
            ])
            self.assertEqual(payload["backups"][0]["size_bytes"], second_backup.stat().st_size)
            self.assertIn("modified_at", payload["backups"][0])

    def test_settings_command_updates_proposal_cooldown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "paper_state.json"
            env = os.environ.copy()
            self.run_cli(["init", "--balance", "500", "--state-path", str(state_path)], env)

            before = self.run_cli(["settings", "--state-path", str(state_path)], env)
            self.assertEqual(before["settings"]["proposal_cooldown_seconds"], 900)

            updated = self.run_cli([
                "settings", "--proposal-cooldown-seconds", "120", "--state-path", str(state_path)
            ], env)
            self.assertTrue(updated["updated"])
            self.assertEqual(updated["settings"]["proposal_cooldown_seconds"], 120)

            status = self.run_cli(["status", "--no-market", "--state-path", str(state_path)], env)
            self.assertEqual(status["proposal_control"]["cooldown_seconds"], 120)

    def test_preflight_passes_for_initialized_state_without_market(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "paper_state.json"
            env = os.environ.copy()
            self.run_cli(["init", "--balance", "500", "--state-path", str(state_path)], env)

            payload = self.run_cli([
                "preflight", "--mode", "tick", "--no-market", "--state-path", str(state_path)
            ], env)

            self.assertEqual(payload["status"], "pass")
            self.assertTrue(payload["can_start_auto"])
            self.assertEqual(payload["mode"], "tick")

    def test_preflight_warns_when_scan_is_in_cooldown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "paper_state.json"
            env = os.environ.copy()
            self.run_cli(["init", "--balance", "500", "--state-path", str(state_path)], env)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["last_proposal_at"] = paper_bot.utc_now()
            state["last_proposal_status"] = "wait"
            state_path.write_text(json.dumps(state), encoding="utf-8")

            payload = self.run_cli([
                "preflight", "--mode", "scan", "--no-market", "--state-path", str(state_path)
            ], env)

            self.assertEqual(payload["status"], "warn")
            self.assertTrue(payload["can_start_auto"])
            self.assertIn("proposal_cooldown", [check["name"] for check in payload["checks"]])

    def test_preflight_fails_for_scan_when_risk_locked(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "paper_state.json"
            env = os.environ.copy()
            self.run_cli(["init", "--balance", "500", "--state-path", str(state_path)], env)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["closed_trades"].append({
                "closed_at": paper_bot.today_utc() + "T00:00:00Z",
                "realized_pnl": -10.01,
            })
            state_path.write_text(json.dumps(state), encoding="utf-8")

            payload = self.run_cli([
                "preflight", "--mode", "scan", "--no-market", "--state-path", str(state_path)
            ], env)

            self.assertEqual(payload["status"], "fail")
            self.assertFalse(payload["can_start_auto"])
            failed_names = [check["name"] for check in payload["checks"] if check["status"] == "fail"]
            self.assertIn("risk_lock", failed_names)

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
            self.assertIn("equity_snapshot", tick)
            status = self.run_cli(["status", "--no-market", "--state-path", str(state_path)], env)
            self.assertTrue(status["ok"])
            self.assertIn("performance", status)
            self.assertGreaterEqual(len(status["equity_snapshots"]), 1)

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

    def test_scan_ticks_then_generates_proposal_with_fixtures(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            state_path = tmp / "paper_state.json"
            analysis_path = tmp / "analysis.json"
            market_path = tmp / "market.json"
            analysis_path.write_text(json.dumps(FIXTURE_ANALYSIS), encoding="utf-8")
            market_path.write_text(json.dumps({
                "candle": {
                    "time": 1779479580000,
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
                    "timestamp": 1779479580000,
                }
            }), encoding="utf-8")
            env = os.environ.copy()
            env["PAPER_BOT_ANALYSIS_FIXTURE"] = str(analysis_path)
            env["PAPER_BOT_MARKET_FIXTURE"] = str(market_path)
            self.run_cli(["init", "--balance", "500", "--state-path", str(state_path)], env)
            scan = self.run_cli([
                "scan", "--symbol", "BTCUSDT", "--side", "short", "--state-path", str(state_path)
            ], env)
            self.assertTrue(scan["ok"])
            self.assertEqual(scan["tick"]["status"], "processed")
            self.assertEqual(scan["proposal"]["status"], "placeable")
            stored = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(len([p for p in stored["pending_plans"] if p["status"] == "pending"]), 1)

    def test_propose_cooldown_skips_repeated_analysis_without_force(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            state_path = tmp / "paper_state.json"
            analysis_path = tmp / "wait_analysis.json"
            analysis_path.write_text(json.dumps(WAIT_ANALYSIS), encoding="utf-8")
            env = os.environ.copy()
            env["PAPER_BOT_ANALYSIS_FIXTURE"] = str(analysis_path)

            self.run_cli(["init", "--balance", "500", "--state-path", str(state_path)], env)
            first = self.run_cli([
                "propose", "--symbol", "BTCUSDT", "--side", "short", "--state-path", str(state_path)
            ], env)
            self.assertEqual(first["status"], "wait")

            blocked_env = os.environ.copy()
            blocked_env["PAPER_BOT_ANALYSIS_FIXTURE"] = str(tmp / "missing_analysis.json")
            second = self.run_cli([
                "propose", "--symbol", "BTCUSDT", "--side", "short", "--state-path", str(state_path)
            ], blocked_env)
            self.assertEqual(second["status"], "cooldown")
            self.assertGreater(second["cooldown_remaining_seconds"], 0)

            status = self.run_cli(["status", "--no-market", "--state-path", str(state_path)], env)
            self.assertIn("cooldown", status["proposal_control"]["blockers"])

            forced = self.run_cli([
                "propose", "--symbol", "BTCUSDT", "--side", "short", "--force", "--state-path", str(state_path)
            ], env)
            self.assertEqual(forced["status"], "wait")

    def test_pause_blocks_propose_before_market_calls(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "paper_state.json"
            env = os.environ.copy()
            init = self.run_cli(["init", "--balance", "500", "--state-path", str(state_path)], env)
            self.assertTrue(init["ok"])
            paused = self.run_cli([
                "pause", "--reason", "manual_test", "--state-path", str(state_path)
            ], env)
            self.assertEqual(paused["status"], "paused")
            proposal = self.run_cli([
                "propose", "--symbol", "BTCUSDT", "--side", "short", "--state-path", str(state_path)
            ], env)
            self.assertEqual(proposal["status"], "paused")
            self.assertEqual(proposal["pause_reason"], "manual_test")
            resumed = self.run_cli([
                "resume", "--reason", "manual_test_done", "--state-path", str(state_path)
            ], env)
            self.assertEqual(resumed["status"], "resumed")
            status = self.run_cli(["status", "--no-market", "--state-path", str(state_path)], env)
            self.assertFalse(status["trading_paused"])

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
