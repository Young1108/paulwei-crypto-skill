# 测试记录

- 日期：2026-05-29 10:32（中国时区）
- 执行者：Codex分析AI
- 范围：BTC Paper 机器人账本导出与权益曲线

## 结果

- `env PYTHONPYCACHEPREFIX=/private/tmp/paulwei-pycache python3 -m py_compile scripts/analyze.py scripts/paper_bot.py scripts/paper_server.py`：通过。
- `python3 -m unittest tests/test_paper_bot.py tests/test_paper_server.py`：18 个测试通过。
- 临时服务 `http://127.0.0.1:8788/api/health`：返回合法 JSON。
- 临时服务 `POST /api/init`：创建 500U paper 账本成功。
- 临时服务 `GET /api/export/state`：返回 `ok=true`、`paper_only=true`、`command=export/state` 和完整 `ledger`。
- 前端静态资源检查：`index.html` 包含“导出账本”和 `equityCurveCanvas`；`app.js` 包含 `renderEquityCurve()` 与导出处理逻辑。
- Headless Playwright 打开 `http://127.0.0.1:8788/`：页面标题为 `BTC Paper 交易`，导出按钮、权益曲线 canvas、paper-only 提示和“绩效 / 历史”均可见。
- 临时服务验证完成后已停止。

---

- 日期：2026-05-29 10:49（中国时区）
- 执行者：Codex分析AI
- 范围：BTC Paper 机器人手动熔断 pause/resume

## 结果

- `env PYTHONPYCACHEPREFIX=/private/tmp/paulwei-pycache python3 -m py_compile scripts/analyze.py scripts/paper_bot.py scripts/paper_server.py`：通过。
- `python3 -m unittest tests/test_paper_bot.py tests/test_paper_server.py`：20 个测试通过。
- 单测验证：`pause` 后 `propose` 返回 `status=paused`，不会进入行情分析路径；`resume` 后 `status` 返回 `trading_paused=false`。
- 临时服务 `POST /api/pause`：返回 `status=paused` 和 `trading_paused=true`。
- 临时服务 `POST /api/resume`：返回 `status=resumed` 和 `trading_paused=false`。
- Headless Playwright 打开 `http://127.0.0.1:8788/`：暂停按钮、恢复按钮、导出按钮、权益曲线 canvas 和 paper-only 提示均可见。

---

- 日期：2026-05-29 11:00（中国时区）
- 执行者：Codex分析AI
- 范围：BTC Paper Web server 独立账本路径

## 结果

- `env PYTHONPYCACHEPREFIX=/private/tmp/paulwei-pycache python3 -m py_compile scripts/analyze.py scripts/paper_bot.py scripts/paper_server.py`：通过。
- `python3 -m unittest tests/test_paper_bot.py tests/test_paper_server.py`：21 个测试通过。
- 单测验证：`AutoTickController` 会把配置的 `state_path` 传给 `paper_bot.command_tick()`。
- 临时服务以 `--state-path /private/tmp/paulwei-paper-state-path-1100.json` 启动，`POST /api/init` 返回该隔离账本路径。
- `GET /api/export/state` 从隔离账本返回 `paper_only=true` 和 500U paper 账本。
- 默认 `data/paper_state.json` 验证前后 mtime 均为 `1780023164`，未被本轮运行级验证改动。
- Headless Playwright 打开隔离账本服务页面，暂停按钮、导出按钮、权益曲线 canvas 和 paper-only 提示均可见。

---

- 日期：2026-05-29 11:11（中国时区）
- 执行者：Codex分析AI
- 范围：BTC Paper 机器人风险摘要与事件面板

## 结果

- `env PYTHONPYCACHEPREFIX=/private/tmp/paulwei-pycache python3 -m py_compile scripts/analyze.py scripts/paper_bot.py scripts/paper_server.py`：通过。
- `python3 -m unittest tests/test_paper_bot.py tests/test_paper_server.py`：22 个测试通过。
- 单测验证：500U 账户下标准风险为 2.5U、最大风险为 5U、日亏损上限为 10U、亏损 3U 后剩余额度为 7U。
- 隔离账本临时服务 `POST /api/status` 返回 `risk_summary.standard_risk_usdt=2.5`、`daily_loss_remaining_usdt=10.0`、`max_leverage=3.0`。
- Headless Playwright 打开隔离账本服务页面，确认“风险 / 事件”面板、标准风险、日亏损余量、控制状态和 paper-only 提示可见。

---

- 日期：2026-05-30 23:14（中国时区）
- 执行者：Codex分析AI
- 范围：BTC Paper 机器人 scan 周期

## 结果

- `env PYTHONPYCACHEPREFIX=/private/tmp/paulwei-pycache python3 -m py_compile scripts/analyze.py scripts/paper_bot.py scripts/paper_server.py`：通过。
- `python3 -m unittest tests/test_paper_bot.py tests/test_paper_server.py`：23 个测试通过。
- 单测验证：`scan` 会先执行 `tick`，再生成 `placeable` 草案，并只留下待确认计划，不自动挂单。
- 隔离账本临时服务 `POST /api/scan`：返回 `command=scan`、`tick.status=processed`、`proposal.status=placeable`。
- Headless Playwright 打开隔离账本服务页面，确认“扫描一次”按钮、风险面板和 paper-only 提示可见。

---

- 日期：2026-05-31 03:05（中国时区）
- 执行者：Codex分析AI
- 范围：BTC Paper 自动运行 Scan 模式

## 结果

- `env PYTHONPYCACHEPREFIX=/private/tmp/paulwei-pycache python3 -m py_compile scripts/analyze.py scripts/paper_bot.py scripts/paper_server.py`：通过。
- `python3 -m unittest tests/test_paper_bot.py tests/test_paper_server.py`：25 个测试通过。
- 单测验证：自动运行 `scan` 模式会调用 `command_scan` 参数集，非法模式 `place` 会被拒绝。
- 隔离账本临时服务 `POST /api/auto/start` 使用 `mode=scan` 返回 `mode=scan`，停止后 `last_result_status=placeable`、`tick_count=1`。
- Headless Playwright 打开隔离账本服务页面，确认自动运行模式下拉框包含 `tick` 和 `scan`。

---

- 日期：2026-05-31 13:22（中国时区）
- 执行者：Codex分析AI
- 范围：BTC Paper init 重置前账本备份

## 结果

- `env PYTHONPYCACHEPREFIX=/private/tmp/paulwei-pycache python3 -m py_compile scripts/analyze.py scripts/paper_bot.py scripts/paper_server.py`：通过。
- `python3 -m unittest tests/test_paper_bot.py tests/test_paper_server.py`：26 个测试通过。
- 单测验证：第二次 `init` 会返回 `backup_path`，备份文件保留旧账本 `initial_balance=500`，当前账本重置为 `initial_balance=600`。
- 隔离账本临时服务连续执行两次 `POST /api/init`：第一次 `backup_path=null`，第二次返回 `/private/tmp/backups/...json`。
- 备份文件内容验证：`initial_balance=500.0`。

---

- 日期：2026-05-31 13:33（中国时区）
- 执行者：Codex分析AI
- 范围：BTC Paper 账本备份保留策略

## 结果

- `env PYTHONPYCACHEPREFIX=/private/tmp/paulwei-pycache python3 -m py_compile scripts/analyze.py scripts/paper_bot.py scripts/paper_server.py`：通过。
- `python3 -m unittest tests/test_paper_bot.py tests/test_paper_server.py`：27 个测试通过。
- 单测验证：同名账本备份超过 20 个时，会删除最旧 2 个并保留最新 20 个。

---

- 日期：2026-05-31 20:50（中国时区）
- 执行者：Codex分析AI
- 范围：提交前验证

## 结果

- `env PYTHONPYCACHEPREFIX=/private/tmp/paulwei-pycache python3 -m py_compile scripts/analyze.py scripts/paper_bot.py scripts/paper_server.py .agents/skills/paulwei-crypto/scripts/paper_bot.py .agents/skills/paulwei-crypto/scripts/paper_server.py`：通过。
- `git diff --check`：通过。
- `python3 -m unittest tests/test_paper_bot.py tests/test_paper_server.py`：27 个测试通过。
- 静态敏感词扫描：未发现真实 API Key、私钥、助记词或交易凭据。

---

- 日期：2026-05-31 21:05（中国时区）
- 执行者：Codex分析AI
- 范围：BTC Paper 账本备份只读列表

## 结果

- `env PYTHONPYCACHEPREFIX=/private/tmp/paulwei-pycache python3 -m py_compile scripts/analyze.py scripts/paper_bot.py scripts/paper_server.py .agents/skills/paulwei-crypto/scripts/paper_bot.py .agents/skills/paulwei-crypto/scripts/paper_server.py`：通过。
- `git diff --check`：通过。
- `python3 -m unittest tests/test_paper_bot.py tests/test_paper_server.py`：29 个测试通过。
- 单测验证：`backups` CLI 按最新优先返回备份元数据；server 备份索引 payload 返回 `command=backups`。
- 隔离账本临时服务连续执行两次 `POST /api/init` 后，`GET /api/backups` 返回 1 个备份、`retention_count=20`。
- Headless Playwright 打开隔离账本服务页面，确认“账本备份”面板、“刷新备份”按钮、备份数量和 paper-only 提示可见。

---

- 日期：2026-05-31 22:46（中国时区）
- 执行者：Codex分析AI
- 范围：BTC Paper 草案生成冷却控制

## 结果

- `env PYTHONPYCACHEPREFIX=/private/tmp/paulwei-pycache python3 -m py_compile scripts/analyze.py scripts/paper_bot.py scripts/paper_server.py .agents/skills/paulwei-crypto/scripts/paper_bot.py .agents/skills/paulwei-crypto/scripts/paper_server.py`：通过。
- `git diff --check`：通过。
- `python3 -m unittest tests/test_paper_bot.py tests/test_paper_server.py`：31 个测试通过。
- 单测验证：重复 `propose` 在冷却期直接返回 `status=cooldown`，不会调用行情分析；`--force` 可人工绕过。
- 隔离账本临时服务 `POST /api/status` 返回 `proposal_control.cooldown_seconds=900` 和 `can_propose=true`。
- Headless Playwright 打开隔离账本服务页面，确认“草案冷却”指标、备份面板和 paper-only 提示可见。

---

- 日期：2026-05-31 23:17（中国时区）
- 执行者：Codex分析AI
- 范围：BTC Paper 自动运行连续错误熔断

## 结果

- `env PYTHONPYCACHEPREFIX=/private/tmp/paulwei-pycache python3 -m py_compile scripts/analyze.py scripts/paper_bot.py scripts/paper_server.py .agents/skills/paulwei-crypto/scripts/paper_bot.py .agents/skills/paulwei-crypto/scripts/paper_server.py`：通过。
- `git diff --check`：通过。
- `python3 -m unittest tests/test_paper_bot.py tests/test_paper_server.py`：33 个测试通过。
- 单测验证：自动运行连续 3 次错误后进入 `halted_error`；成功 tick 会重置连续错误计数。
- 隔离账本临时服务 `POST /api/auto/status` 返回 `consecutive_error_count=0`、`max_consecutive_errors=3`、`halted_at=null`。
- Headless Playwright 打开隔离账本服务页面，确认自动状态显示“连续错误 0/3”、草案冷却、备份面板和 paper-only 提示。

---

- 日期：2026-06-01 00:24（中国时区）
- 执行者：Codex分析AI
- 范围：BTC Paper 机器人安全范围配置化

## 结果

- `env PYTHONPYCACHEPREFIX=/private/tmp/paulwei-pycache python3 -m py_compile scripts/analyze.py scripts/paper_bot.py scripts/paper_server.py .agents/skills/paulwei-crypto/scripts/paper_bot.py .agents/skills/paulwei-crypto/scripts/paper_server.py`：通过。
- `git diff --check`：通过。
- `python3 -m unittest tests/test_paper_bot.py tests/test_paper_server.py`：36 个测试通过。
- 单测验证：草案冷却设置可更新到 120 秒；冷却范围 60-3600 秒；自动连续错误阈值范围 1-10 次。
- 隔离账本临时服务 `POST /api/settings` 将 `proposal_cooldown_seconds` 更新为 120。
- 隔离账本临时服务 `POST /api/auto/start` 使用 `max_consecutive_errors=5` 启动成功。
- 隔离账本临时服务 `POST /api/status` 返回 `proposal_control.cooldown_seconds=120` 和 `auto_tick.max_consecutive_errors=5`。
- Headless Playwright 打开隔离账本服务页面，确认冷却输入为 `120`、错误阈值输入为 `5`、保存设置按钮和 paper-only 提示可见。

---

- 日期：2026-06-01 10:09（中国时区）
- 执行者：Codex分析AI
- 范围：BTC Paper 跨进程账本文件锁

## 结果

- `env PYTHONPYCACHEPREFIX=/private/tmp/paulwei-pycache python3 -m py_compile scripts/analyze.py scripts/paper_bot.py scripts/paper_server.py .agents/skills/paulwei-crypto/scripts/paper_bot.py .agents/skills/paulwei-crypto/scripts/paper_server.py`：通过。
- `git diff --check`：通过。
- `python3 -m unittest tests/test_paper_bot.py tests/test_paper_server.py`：38 个测试通过。
- 单测验证：`state_file_lock()` 创建 sidecar lock 文件；CLI `init` 后锁文件存在；server `run_paper_command()` 在锁内执行。
- 隔离账本临时服务执行 `POST /api/init` 与 `POST /api/settings` 后，`/private/tmp/paulwei-lock-view.json.lock` 存在。
- Headless Playwright 打开隔离账本服务页面，确认冷却输入为 `180`、保存设置按钮和 paper-only 提示可见。

---

- 日期：2026-06-01 10:25（中国时区）
- 执行者：Codex分析AI
- 范围：BTC Paper 自动运行前自检

## 结果

- `env PYTHONPYCACHEPREFIX=/private/tmp/paulwei-pycache python3 -m py_compile scripts/analyze.py scripts/paper_bot.py scripts/paper_server.py .agents/skills/paulwei-crypto/scripts/paper_bot.py .agents/skills/paulwei-crypto/scripts/paper_server.py`：通过。
- `git diff --check`：通过。
- `python3 -m unittest tests/test_paper_bot.py tests/test_paper_server.py`：41 个测试通过。
- 单测验证：初始化账本自检通过；scan 冷却期返回 warning；scan 在日损锁定时返回 fail。
- 隔离账本临时服务 `POST /api/preflight` 使用 `mode=scan,no_market=true` 返回 `status=pass`、`can_start_auto=true`。
- Headless Playwright 打开隔离账本服务页面，确认“运行前自检”按钮、自检状态文本、自动运行状态和 paper-only 提示可见。

---

- 日期：2026-06-01 10:49（中国时区）
- 执行者：Codex分析AI
- 范围：BTC Paper 自检结果明细列表与提交前验证

## 结果

- 临时服务端口 `8788`：无监听进程。

---

- 日期：2026-06-01 11:10（中国时区）
- 执行者：Codex分析AI
- 范围：BTC Paper 自动运行熔断重置

## 结果

- `env PYTHONPYCACHEPREFIX=/private/tmp/paulwei-pycache python3 -m py_compile scripts/analyze.py scripts/paper_bot.py scripts/paper_server.py .agents/skills/paulwei-crypto/scripts/paper_bot.py .agents/skills/paulwei-crypto/scripts/paper_server.py`：通过。
- `env PYTHONPYCACHEPREFIX=/private/tmp/paulwei-pycache python3 -m unittest tests/test_paper_bot.py tests/test_paper_server.py`：43 个测试通过。
- `git diff --check`：通过。
- 单测验证：连续错误熔断后 `reset_halt()` 清除 `halted_at`、`halt_reason`、`last_error` 和 `consecutive_error_count`，并保留累计 `error_count`。
- 隔离账本临时服务 `POST /api/auto/reset` 返回合法 JSON，`command=auto/reset`、`running=false`、`last_result_status=reset`。
- Headless Playwright 打开隔离账本服务页面，确认“重置熔断”按钮可见，paper-only 提示仍可见。
- 临时服务端口 `8788`：无监听进程。
- Headless Playwright 使用隔离账本页面注入自检样例 payload，确认：
  - 自检状态文本显示 `自检有警告 · 失败 1 · 警告 1`。
  - 页面渲染 3 条 `.preflight-check` 明细。
  - `.warn` 与 `.fail` 状态样式可见。
  - paper-only 提示仍可见。
- `env PYTHONPYCACHEPREFIX=/private/tmp/paulwei-pycache python3 -m py_compile scripts/analyze.py scripts/paper_bot.py scripts/paper_server.py .agents/skills/paulwei-crypto/scripts/paper_bot.py .agents/skills/paulwei-crypto/scripts/paper_server.py`：通过。
- `env PYTHONPYCACHEPREFIX=/private/tmp/paulwei-pycache python3 -m unittest tests/test_paper_bot.py tests/test_paper_server.py`：41 个测试通过。
- `git diff --check`：通过。
- 敏感赋值形态扫描：无命中。

---

- 日期：2026-06-01 10:58（中国时区）
- 执行者：Codex分析AI
- 范围：BTC Paper 自检处理建议

## 结果

- `env PYTHONPYCACHEPREFIX=/private/tmp/paulwei-pycache python3 -m py_compile scripts/analyze.py scripts/paper_bot.py scripts/paper_server.py .agents/skills/paulwei-crypto/scripts/paper_bot.py .agents/skills/paulwei-crypto/scripts/paper_server.py`：通过。
- `env PYTHONPYCACHEPREFIX=/private/tmp/paulwei-pycache python3 -m unittest tests/test_paper_bot.py tests/test_paper_server.py`：42 个测试通过。
- `git diff --check`：通过。
- 单测验证：preflight 检查项包含 `remediation`；草案冷却 warning 和日损锁 failure 返回明确处理建议；server 自检失败消息包含处理建议。
- Headless Playwright 打开隔离账本服务页面，注入自检样例 payload 后确认：
  - 页面渲染 3 条 `.preflight-check` 明细。
  - 页面渲染 3 条 `.remediation` 处理建议。
  - `.fail` 状态样式可见。
  - paper-only 提示仍可见。
- 临时服务端口 `8788`：无监听进程。
