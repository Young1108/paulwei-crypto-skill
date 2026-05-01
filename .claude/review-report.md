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
