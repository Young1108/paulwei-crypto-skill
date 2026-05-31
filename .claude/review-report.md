# paulwei-crypto-skill 安全审查报告

- 生成时间：2026-05-02 03:06（中国时区）
- 执行者：Codex分析AI
- 审查范围：`SKILL.md`、`scripts/analyze.py`、`references/framework.md`、`README.md`、`evals/evals.json`
- 结论：退回
- 安全评分：68/100

## 工具降级说明

任务指令要求使用 `sequential-thinking` 和 `code-index`。当前环境未提供这两个工具，也未提供 `exa`。本次使用 `rg`、`sed`、`nl`、`python3 -m py_compile`、`python3 -m json.tool`、`curl` 和人工结构化审查替代，并在 `operations-log.md` 记录。

## 摘要

仓库规模较小，未发现恶意下单接口、API Key、私钥、密码、`shell=True`、`eval/exec` 或文件写入型后门。主要风险不在“已有恶意代码”，而在 skill 会把用户输入转化为本地命令和个性化期货交易建议：缺少 symbol 白名单、HTTP 错误透明处理、金融建议边界和越界读取防护。

## 发现的问题

### SEC-001：命令参数插值缺少白名单约束（高）

- 位置：`SKILL.md:88-91`
- 证据：文档要求运行 `python3 scripts/analyze.py {SYMBOL}`，但没有强制 `SYMBOL` 必须通过安全正则，也没有要求用参数数组或 shell 安全引用。
- 影响：脚本内部使用 `sys.argv` 本身不触发 shell 注入，但执行代理通常会把 skill 示例变成 shell 命令。如果用户输入被错误提取为 symbol 并拼接，可能追加 shell metacharacters。
- 建议：在 `SKILL.md` 增加硬规则：只允许 `^[A-Z0-9]{2,20}USDT$`；别名映射失败时拒绝执行；调用脚本时必须把 symbol 作为独立参数传入。

### SEC-002：脚本未校验 symbol，query 参数手工拼接（中高）

- 位置：`scripts/analyze.py:22`、`scripts/analyze.py:252`
- 证据：`symbol = sys.argv[1].upper()` 后直接进入 `fetch()`；`fetch()` 用 `"&".join(f"{k}={v}"...)` 拼 query。
- 影响：恶意或异常 symbol 可污染 query 参数，造成错误数据或不可预期响应。由于域名固定且 `subprocess.run()` 使用 argv 列表，当前未构成 SSRF 或 shell 执行，但会影响数据可信度。
- 建议：增加 symbol 正则和长度校验；用 `urllib.parse.urlencode()` 编码参数；请求失败时输出结构化错误。

### SEC-003：Binance 受限地区响应被误报为交易对不存在（中）

- 位置：`scripts/analyze.py:24-30`、`scripts/analyze.py:264-266`
- 证据：本地运行 `python3 scripts/analyze.py BTCUSDT` 输出 `BTCUSDT not found`；原始 HTTP 响应是 `451 Service unavailable from a restricted location`。
- 影响：有效交易对被误判，会诱导用户或模型使用不透明兜底路径、旧数据或手工计算。在金融场景里，错误来源必须可解释。
- 建议：curl 使用 `--fail-with-body` 或改用标准库 HTTP 客户端读取状态码；对 451/403/429/5xx 分别报错；仅在 Binance 明确 symbol 不存在时返回 not found。

### SEC-004：金融建议边界不足（中）

- 位置：`SKILL.md:220-267`、`SKILL.md:329-335`、`README.md:148`
- 证据：README 末尾有“不构成投资建议”，但 skill 输出模板要求具体入场、仓位、杠杆和“可以执行”。该免责声明没有成为运行时强制输出或安全约束。
- 影响：skill 可能生成个性化期货交易建议，且用户所在法域、交易所可用性、杠杆适当性和绕过限制风险未被显式处理。
- 建议：把边界写进 `SKILL.md`：只做教育性分析与风险校验；不得替用户决策；不得建议绕过地区限制；行情不可用时不制定策略；全仓/高杠杆只输出降风险方案。

### SEC-005：参考文档包含 skill 外绝对路径（低中）

- 位置：`references/framework.md:4`、`references/framework.md:194`
- 证据：引用 `/root/trading/paulwei/analysis/ANALYSIS.md`。
- 影响：安装到其他环境后，模型可能尝试读取 skill 目录外路径。若该路径存在敏感内容，会造成越界读取风险。
- 建议：删除绝对路径，改为 repo 内相对路径或公开资料链接。

## 验证记录

- `python3 -m py_compile scripts/analyze.py`：通过。
- `python3 -m json.tool evals/evals.json`：通过。
- 静态检索：未发现 API Key、SECRET、TOKEN、`.ssh`、`shell=True`、`eval()`、`exec()`、`pickle`。
- 运行 `python3 scripts/analyze.py BTCUSDT`：失败，脚本输出交易对不存在。
- 原始 Binance 请求：HTTP 451，原因是 restricted location，不是交易对不存在。

## 评分说明

该 skill 未表现出恶意行为，基础依赖也较少，这是加分项。但它的触发范围很宽，会执行网络请求并生成具体期货交易计划。对这种 skill，输入校验、错误透明、合规边界和失败关闭必须更强。建议修复 SEC-001 至 SEC-004 后再考虑通过。

## 建议修复顺序

1. 先修 `scripts/analyze.py`：symbol 正则、URL 编码、HTTP 状态处理、受限地区错误。
2. 再修 `SKILL.md`：安全调用约束、行情不可用时失败关闭、金融免责声明和合规边界。
3. 清理 `references/framework.md` 中的绝对路径。
4. 增加 eval：恶意 symbol、无效 symbol、HTTP 451/429、空数组响应、高杠杆交易评估。

---

# BTC Paper 机器人完善审查

- 生成时间：2026-05-27 11:29（中国时区）
- 执行者：Codex分析AI
- 审查范围：`scripts/paper_bot.py`、`scripts/paper_server.py`、`web/`、`tests/test_paper_bot.py`、`README.md`、`SKILL.md`
- 结论：通过，保留 v1 范围限制
- 综合评分：86/100

## 已修复问题

1. `tick` 幂等性不足：新增 `last_processed_candle_time`，同一根 1 分钟 K 线重复 tick 时只刷新权益，不重复成交、止盈或止损。
2. 同根 K 线乐观成交：新挂单记录 `created_candle_time`，不会用创建所在 K 线已经发生过的 high/low 触发成交。
3. 缺少取消控制：新增 CLI `cancel`、API `/api/cancel` 和前端“取消草案/挂单”按钮。
4. 计划过期未执行：新增草案和开放入场挂单过期失效处理。
5. 旧账本迁移：缺少 `expires_at` 的旧开放挂单按 `created_at + 4小时` 自动过期。
6. 状态可观测性不足：`status` 输出行情状态、行情延迟、上次 tick、上次 K 线、上次账本动作。

## 验证记录

- `python3 -m py_compile scripts/analyze.py scripts/paper_bot.py scripts/paper_server.py`：通过。
- `python3 -m unittest tests/test_paper_bot.py`：12 个测试通过。
- `python3 scripts/paper_bot.py status`：通过，MEXC 行情 `market_status=live`，行情延迟约 2.7 秒。
- `curl http://127.0.0.1:8787/api/health`：通过。
- 浏览器打开 `http://127.0.0.1:8787`：页面显示“取消草案/挂单”、行情状态、BTC 实时价和 paper-only 提示。
- 已安装 skill 目录 `paper_bot.py` 与 `paper_server.py` 编译通过。
- 已安装 skill 目录 `status --no-market`：通过。

## 剩余不足

- v1 仍只支持 BTCUSDT/MEXC/paper-only。
- 暂无权益曲线、订单历史详情、策略参数回测。
- 前端只自动刷新状态，不自动推进 `tick`；如需无人值守 paper，需要单独设计定时 tick 和失败告警。
- 当前策略只覆盖做空草案，未实现多头策略与横盘不交易的更细粒度规则。

## 建议

通过当前 v1 完善项。下一阶段应优先补历史页面、权益曲线、定时 tick 与失败告警，不应接入真实账户或密钥。

---

# BTC Paper 自动运行层审查

- 生成时间：2026-05-29 01:37（中国时区）
- 执行者：Codex分析AI
- 审查范围：`scripts/paper_server.py`、`web/`、`tests/test_paper_server.py`、`README.md`、`SKILL.md`
- 结论：通过，继续保持 paper-only
- 综合评分：88/100

## 已完成

1. 新增本地 `AutoTickController`，支持在 paper server 进程内自动调用 `tick`。
2. 新增 `/api/auto/start`、`/api/auto/stop`、`/api/auto/status`。
3. `/api/status` 与 `/api/health` 返回自动运行状态，便于前端和外部工具观测。
4. 前端新增自动运行面板、间隔输入、启动和停止控制。
5. 自动 tick 失败时只记录错误，不使用旧行情模拟交易。

## 验证记录

- `env PYTHONPYCACHEPREFIX=/private/tmp/paulwei-pycache python3 -m py_compile scripts/analyze.py scripts/paper_bot.py scripts/paper_server.py`：通过。
- `python3 -m unittest tests/test_paper_bot.py tests/test_paper_server.py`：15 个测试通过。
- 临时服务 `http://127.0.0.1:8788`：auto API 启停验证通过。
- 浏览器验证：自动运行面板、启动自动 tick、停止按钮可见。

## 剩余风险

- 自动运行依赖本地 server 生命周期，不是独立守护进程。
- 当前只做 tick 自动推进，不自动生成新计划；这是刻意保守边界。
- 无权益曲线、历史订单页和策略回测，仍不足以评估长期策略质量。

---

# BTC Paper 绩效与历史审计层审查

- 生成时间：2026-05-29 01:50（中国时区）
- 执行者：Codex分析AI
- 审查范围：`scripts/paper_bot.py`、`web/`、`tests/test_paper_bot.py`、`README.md`、`SKILL.md`
- 结论：通过，仍保持 paper-only
- 综合评分：90/100

## 已完成

1. 新增 `equity_snapshots`，有效 tick 会记录权益快照。
2. 新增 `performance_summary()`，输出交易次数、胜率、利润因子、已实现/未实现/净盈亏、当前回撤。
3. `status` 返回最近权益快照、最近已平仓交易和绩效统计。
4. 前端新增“绩效 / 历史”面板，展示核心绩效和最近历史。
5. 测试覆盖绩效统计与 tick 快照输出。

## 验证记录

- `env PYTHONPYCACHEPREFIX=/private/tmp/paulwei-pycache python3 -m py_compile scripts/analyze.py scripts/paper_bot.py scripts/paper_server.py`：通过。
- `python3 -m unittest tests/test_paper_bot.py tests/test_paper_server.py`：16 个测试通过。
- 临时服务 `/api/status` 返回 `performance`、`closed_trades`、`equity_snapshots`。
- 浏览器验证“绩效 / 历史”面板可见。

## 剩余风险

- 尚未实现权益折线图、历史筛选、交易导出和回测对比。
- 绩效指标基于 paper 成交账本，不能代表真实成交滑点或真实账户结果。

---

# BTC Paper 导出与权益曲线审查

- 生成时间：2026-05-29 10:32（中国时区）
- 执行者：Codex分析AI
- 审查范围：`scripts/paper_server.py`、`web/`、`tests/test_paper_server.py`、`README.md`、`SKILL.md`
- 结论：通过，继续保持 paper-only
- 综合评分：91/100

## 已完成

1. 新增 `GET /api/export/state`，返回 `paper_only=true` 和完整本地 paper 账本。
2. 导出 payload 由 `export_state_payload()` 生成，测试可直接覆盖，不依赖真实 HTTP 服务。
3. 前端新增“导出账本”按钮，可下载 JSON 文件用于复盘。
4. 前端新增权益曲线 canvas，用最近权益快照显示权益变化。
5. 测试覆盖导出 payload，并检查不包含 `api_key`、`private_key`、`mnemonic` 等真实账户敏感字段。

## 验证记录

- `env PYTHONPYCACHEPREFIX=/private/tmp/paulwei-pycache python3 -m py_compile scripts/analyze.py scripts/paper_bot.py scripts/paper_server.py`：通过。
- `python3 -m unittest tests/test_paper_bot.py tests/test_paper_server.py`：18 个测试通过。
- 临时服务 `/api/health`、`POST /api/init`、`GET /api/export/state` 均返回合法 JSON。
- 前端静态资源包含“导出账本”、`equityCurveCanvas` 和 `renderEquityCurve()`。
- Headless Playwright 打开本地页面，确认导出按钮、权益曲线 canvas、paper-only 提示和“绩效 / 历史”可见。

## 剩余风险

- 权益曲线只使用当前 `status` 返回的最近 100 条快照，不是长期报表。
- 导出是完整本地 paper 账本，没有筛选和脱敏配置；当前账本设计不保存真实凭据，因此可接受。
- 仍未实现回测、多头策略、多币种 paper 和独立守护进程。

---

# BTC Paper 手动熔断控制审查

- 生成时间：2026-05-29 10:49（中国时区）
- 执行者：Codex分析AI
- 审查范围：`scripts/paper_bot.py`、`scripts/paper_server.py`、`web/`、`tests/test_paper_bot.py`、`README.md`、`SKILL.md`
- 结论：通过，适合作为 paper 机器人控制面基础能力
- 综合评分：92/100

## 已完成

1. 新增 `pause` / `resume` CLI 命令，支持人工暂停和恢复新草案生成。
2. `propose` 在 `trading_paused=true` 时直接返回 `status=paused`，不触发行情分析或计划生成。
3. `tick` 不受暂停影响，仍可推进已有模拟挂单、止盈止损和权益更新。
4. server 新增 `/api/pause`、`/api/resume`，前端新增“暂停新草案 / 恢复”控制。
5. 暂停/恢复事件写入 `risk_events`，导出账本时可审计。

## 验证记录

- `env PYTHONPYCACHEPREFIX=/private/tmp/paulwei-pycache python3 -m py_compile scripts/analyze.py scripts/paper_bot.py scripts/paper_server.py`：通过。
- `python3 -m unittest tests/test_paper_bot.py tests/test_paper_server.py`：20 个测试通过。
- 单测覆盖暂停后阻止 `propose`，恢复后 `status.trading_paused=false`。
- 临时服务 `/api/pause` 和 `/api/resume` 返回预期 JSON。
- Headless Playwright 验证暂停按钮、恢复按钮、导出按钮和权益曲线 canvas 可见。

## 剩余风险

- 当前是一键暂停新草案，不是完整守护进程熔断；不会停止正在运行的 server 进程。
- 前端暂未提供 `risk_events` 单独过滤视图。

---

# BTC Paper 独立账本路径审查

- 生成时间：2026-05-29 11:00（中国时区）
- 执行者：Codex分析AI
- 审查范围：`scripts/paper_server.py`、`tests/test_paper_server.py`、`README.md`、`SKILL.md`
- 结论：通过，减少本地验证和多实例运行的账本污染风险
- 综合评分：92/100

## 已完成

1. `paper_server.py` 新增 `--state-path`，支持为本地 server 指定独立 paper 账本。
2. 所有 HTTP API 使用同一个 server 级 `paper_state_path`，包括 init、propose、place、pause、resume、cancel、tick、status。
3. `/api/export/state` 使用同一隔离账本路径导出。
4. 自动 tick 通过 `AutoTickController.state_path` 调用同一隔离账本。
5. 文档补充隔离演练账本启动命令。

## 验证记录

- `env PYTHONPYCACHEPREFIX=/private/tmp/paulwei-pycache python3 -m py_compile scripts/analyze.py scripts/paper_bot.py scripts/paper_server.py`：通过。
- `python3 -m unittest tests/test_paper_bot.py tests/test_paper_server.py`：21 个测试通过。
- 单测覆盖自动 tick 传递配置的 `state_path`。
- 临时服务以 `--state-path /private/tmp/paulwei-paper-state-path-1100.json` 启动，API 使用隔离账本。
- 默认 `data/paper_state.json` 验证前后 mtime 均为 `1780023164`，未被本轮运行级验证改动。
- Headless Playwright 确认隔离账本服务页面关键控件可见。

## 剩余风险

- 当前账本路径是 server 启动参数，前端不能动态切换账本。
- 尚未实现多账本对比、归档和回测复用。

---

# BTC Paper 风险摘要与事件面板审查

- 生成时间：2026-05-29 11:11（中国时区）
- 执行者：Codex分析AI
- 审查范围：`scripts/paper_bot.py`、`web/`、`tests/test_paper_bot.py`、`README.md`、`SKILL.md`
- 结论：通过，提升 paper 机器人风险可观测性
- 综合评分：93/100

## 已完成

1. 新增 `risk_summary()`，集中输出单笔风险、日亏损上限、日亏损余量、杠杆上限和控制状态。
2. `status` 返回 `risk_summary`，便于 CLI、Web UI 和外部工具统一读取。
3. 前端新增“风险 / 事件”面板，展示核心风险参数和最近 `risk_events`。
4. 测试覆盖 500U 账户的标准风险、最大风险、日亏损上限和剩余额度计算。

## 验证记录

- `env PYTHONPYCACHEPREFIX=/private/tmp/paulwei-pycache python3 -m py_compile scripts/analyze.py scripts/paper_bot.py scripts/paper_server.py`：通过。
- `python3 -m unittest tests/test_paper_bot.py tests/test_paper_server.py`：22 个测试通过。
- 隔离账本临时服务 `/api/status` 返回预期 `risk_summary`。
- Headless Playwright 确认“风险 / 事件”面板和核心风险指标可见。

## 剩余风险

- 风险事件面板仍是最近事件展示，未做筛选、搜索或分页。
- paper 风险摘要不等价于真实交易所保证金、维持保证金或强平风险。

---

# BTC Paper Scan 周期审查

- 生成时间：2026-05-30 23:14（中国时区）
- 执行者：Codex分析AI
- 审查范围：`scripts/paper_bot.py`、`scripts/paper_server.py`、`web/`、`tests/test_paper_bot.py`、`README.md`、`SKILL.md`
- 结论：通过，符合 paper-only 半自动机器人边界
- 综合评分：93/100

## 已完成

1. 新增 `scan` CLI 命令，执行 `tick -> propose`。
2. `scan` 不会确认挂单，不会真实下单，只可能生成待确认草案。
3. server 新增 `/api/scan`。
4. 前端新增“扫描一次”按钮。
5. 测试覆盖 fixture 行情下 `scan` 先 tick 后生成 `placeable` 草案。

## 验证记录

- `env PYTHONPYCACHEPREFIX=/private/tmp/paulwei-pycache python3 -m py_compile scripts/analyze.py scripts/paper_bot.py scripts/paper_server.py`：通过。
- `python3 -m unittest tests/test_paper_bot.py tests/test_paper_server.py`：23 个测试通过。
- 隔离账本临时服务 `/api/scan` 返回 `tick.status=processed` 和 `proposal.status=placeable`。
- Headless Playwright 确认“扫描一次”按钮可见。

## 剩余风险

- 自动循环仍只自动 tick，不自动 scan；避免无人值守连续生成草案。
- `scan` 依赖实时行情和分析脚本可用，行情失败时会失败关闭。

---

# BTC Paper 自动运行 Scan 模式审查

- 生成时间：2026-05-31 03:05（中国时区）
- 执行者：Codex分析AI
- 审查范围：`scripts/paper_server.py`、`web/`、`tests/test_paper_server.py`、`README.md`、`SKILL.md`
- 结论：通过，仍保持半自动 paper 边界
- 综合评分：93/100

## 已完成

1. 自动运行支持 `tick` 与 `scan` 两种模式。
2. `/api/auto/start` 接收 `mode=tick|scan`，非法模式会被拒绝。
3. `scan` 模式调用 `command_scan`，只执行 `tick -> propose`，不会确认挂单。
4. 前端自动运行面板新增模式选择，并在状态行显示当前模式。
5. 测试覆盖 scan 模式调用和非法模式拒绝。

## 验证记录

- `env PYTHONPYCACHEPREFIX=/private/tmp/paulwei-pycache python3 -m py_compile scripts/analyze.py scripts/paper_bot.py scripts/paper_server.py`：通过。
- `python3 -m unittest tests/test_paper_bot.py tests/test_paper_server.py`：25 个测试通过。
- 隔离账本临时服务验证 `mode=scan` 自动运行，停止后 `last_result_status=placeable`。
- Headless Playwright 确认自动运行模式下拉框包含 `tick` 和 `scan`。

## 剩余风险

- 自动运行仍依赖本地 server 进程，不是独立守护进程。
- scan 模式可能周期性生成待确认草案，但不会自动挂单。

---

# BTC Paper Init 备份审查

- 生成时间：2026-05-31 13:22（中国时区）
- 执行者：Codex分析AI
- 审查范围：`scripts/paper_bot.py`、`tests/test_paper_bot.py`、`README.md`、`SKILL.md`
- 结论：通过，降低误重置导致的模拟账本历史丢失风险
- 综合评分：93/100

## 已完成

1. `init` 在覆盖已有 paper 账本前自动复制旧账本到同目录 `backups/`。
2. `init` 返回 `backup_path`，便于 CLI、Web 日志和审计追踪。
3. 测试覆盖第二次 `init` 的备份文件存在性和内容正确性。
4. 文档明确重置前会自动备份旧 paper JSON。

## 验证记录

- `env PYTHONPYCACHEPREFIX=/private/tmp/paulwei-pycache python3 -m py_compile scripts/analyze.py scripts/paper_bot.py scripts/paper_server.py`：通过。
- `python3 -m unittest tests/test_paper_bot.py tests/test_paper_server.py`：26 个测试通过。
- 隔离账本临时服务连续两次 `/api/init` 验证：第二次返回 `backup_path`。
- 备份文件内容保留旧账本 `initial_balance=500.0`。

## 剩余风险

- 备份文件暂不自动清理，长期运行需要后续增加保留策略。
- 前端暂未提供备份列表或恢复按钮。

---

# BTC Paper 备份保留策略审查

- 生成时间：2026-05-31 13:33（中国时区）
- 执行者：Codex分析AI
- 审查范围：`scripts/paper_bot.py`、`tests/test_paper_bot.py`、`README.md`、`SKILL.md`
- 结论：通过，减少长期运行下备份目录膨胀风险
- 综合评分：94/100

## 已完成

1. 默认每个账本只保留最近 20 个自动备份。
2. 清理范围限定为同名账本在 `backups/` 下的自动备份文件。
3. 测试覆盖超过保留数时删除旧备份并保留最新备份。
4. 文档说明 `init` 备份默认保留最近 20 个。

## 验证记录

- `env PYTHONPYCACHEPREFIX=/private/tmp/paulwei-pycache python3 -m py_compile scripts/analyze.py scripts/paper_bot.py scripts/paper_server.py`：通过。
- `python3 -m unittest tests/test_paper_bot.py tests/test_paper_server.py`：27 个测试通过。

## 剩余风险

- 保留数量仍是代码常量，暂未暴露为 CLI 配置。
- 暂无前端备份管理和恢复能力。
