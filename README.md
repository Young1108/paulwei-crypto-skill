# paulwei-crypto

基于 Paul Wei（[@coolish](https://x.com/coolish)）公开实盘数据逆向工程的加密货币交易辅助 skill。

Paul Wei 是 BitMEX 官方 Hall of Legends 认证交易员，6 年公开实盘：173,058 笔成交，最新调整后财富 52x（相对 2020 年初始基准）。

---

## 安装

```bash
npx skills add https://github.com/hanniballei/paulwei-crypto-skill
```

**前提条件**：
- Python 3.6+（系统通常已有）
- 无需安装任何 Python 第三方库，无需 Binance API Key

**代理说明**：
- 命令行 Python 进程只可靠读取 `HTTPS_PROXY`、`HTTP_PROXY`、`ALL_PROXY` 等标准环境变量，不一定继承系统或客户端的“全局代理”。
- 仅在合规网络和合规市场数据访问条件下配置代理；不要使用代理绕过交易所、地区、KYC 或服务条款限制。

---

## 支持的品种

支持常见 **USDT 永续/Swap 合约**。脚本会并发竞速 MEXC、Bitget、Binance USDT-M、OKX SWAP、Bybit USDT linear 公共行情，使用最快返回完整有效数据的合规数据源。

BTC / ETH / SOL / BNB / XRP / DOGE / ADA / AVAX / LINK / DOT … 及 400+ 其他合约品种。

输入品种时，中英文均可识别：
- `btc` / `BTC` / `bitcoin` / `比特币` → BTCUSDT
- `eth` / `以太坊` → ETHUSDT
- `sol` / `solana` → SOLUSDT

---

## 三个核心场景

### 场景一：市场结构分析

了解某个币种当前处于什么位置。

**触发示例**：
```
分析一下BTC行情
SOL 现在怎样
ETH 市场结构
analyze DOGE
```

**输出内容**：
- 当前价格 & 24h 涨跌幅
- MA7 / MA14 / MA30 均线状态及偏离度（核心判断依据）
- 30日高低区间 & ATR14 日均波幅
- 关键支撑/阻力价位（枢轴点）
- 4小时近期结构（上升 / 下降 / 震荡）
- 资金费率偏向（多头付费 vs 空头付费）
- **周线背景**：周线趋势方向 + 周线MA30偏离（识别日周背离）
- **关键整数价位**：自动识别主要/次要心理价位 + 配套挂单建议
- **综合评分**：做多/做空适宜度（★1-5）+ 主要依据 + 一句话操作建议
- 做多/做空关注区综合判断

### 场景二：交易策略制定

把方向判断转化为可执行的入场、仓位和出场计划。

**触发示例**：
```
我想做多BTC，帮我制定策略
我账户1万，怎么买SOL
帮我规划一个ETH多单
plan a BTC long for $50k account
```

**输出内容**：
- 等待入场区间 & 依据
- 分3批挂单的具体价位（含末三位心理整数）
- 按账户规模计算的仓位大小（标准风险 0.5% 账户净值）
- 多档止损距离对应的名义仓位和杠杆
- 分批减仓计划 & 结构失效清仓条件

### 场景三：交易/策略评估

检查你的交易方案是否符合 Paul Wei 的风险框架。

**触发示例**：
```
我打算用10x杠杆全仓做多，帮我看看合不合适
check my trade: long BTC at 95k, stop at 92k, size 3%
这笔交易合理吗：做多SOL，入场180，止损170，仓位20%账户
```

**输出内容**：
- 6条红线校验（任意一条触发即高危）
- 7条警告校验
- 最佳实践清单
- 综合风险等级 & 执行建议
- 改良方案（保留方向，调整执行）

### 场景四：BTC Paper 合约机器人

用真实 MEXC BTC_USDT 行情模拟合约交易，不连接真实账户，不需要 API Key，不下真实订单。

**命令示例**：
```bash
python3 scripts/paper_bot.py init --balance 500
python3 scripts/paper_bot.py backups
python3 scripts/paper_bot.py settings --proposal-cooldown-seconds 900
python3 scripts/paper_bot.py preflight --mode scan
python3 scripts/paper_bot.py propose --symbol BTCUSDT --side short
python3 scripts/paper_bot.py scan --symbol BTCUSDT --side short
python3 scripts/paper_bot.py place --plan-id <PLAN_ID>
python3 scripts/paper_bot.py pause --reason manual_review
python3 scripts/paper_bot.py resume --reason manual_review_done
python3 scripts/paper_bot.py cancel --all
python3 scripts/paper_bot.py tick
python3 scripts/paper_bot.py status
```

**本地前端**：
```bash
python3 scripts/paper_server.py --host 127.0.0.1 --port 8787
```

然后打开 [http://127.0.0.1:8787](http://127.0.0.1:8787)。

需要隔离演练账本时可以指定独立路径：
```bash
python3 scripts/paper_server.py --host 127.0.0.1 --port 8787 --state-path /private/tmp/btc-paper-demo.json
```

界面按最小流程使用：
1. 需要重开模拟时点“重置 500U 模拟账户”；若旧账本存在，系统会先备份到 `backups/`。
2. 点“生成做空草案”，系统会判断是否值得模拟；也可以点“扫描一次”，先推进 tick 再尝试生成草案。
3. 有草案且你接受风险时，点“确认为模拟挂单”。
4. 不想继续等待时，点“取消草案/挂单”。
5. 需要人工熔断时点“暂停新草案”，恢复后再继续生成新计划。
6. 之后可以手动点“刷新行情并模拟成交”，也可以启动自动运行；自动运行支持 `Tick` 或 `Scan`，`Scan` 只生成待确认草案。

前端会显示 BTC 实时价、24h 涨跌、行情延迟、上次 tick 状态、自动运行状态、挂单距现价、风险摘要、草案冷却、最近风控事件、绩效统计、权益曲线、最近交易历史和账本备份列表，并每 15 秒自动刷新状态。点击“导出账本”可下载完整 paper JSON 账本，用于复盘或审计。若挂单距现价较远，模拟成交不会发生，这是策略等待反弹触发，不是行情失效。

**v1 限制**：
- 只支持 `BTCUSDT` / MEXC `BTC_USDT`
- 只支持 paper 模拟，不支持真实下单或 CEX API 签名
- `init` 重置已有账本前会自动备份旧 paper JSON，并默认只保留最近 20 个备份
- `backups` 和 `/api/backups` 只列出同账本 `backups/` 目录的备份元数据，不恢复、不删除、不修改账本
- 单笔标准风险 `0.5%`，单笔最大风险 `1%`
- 最大模拟杠杆 `3x`
- 日内累计亏损达到 `2%` 后停止生成新计划
- 手动 `pause` 只阻止新草案生成，不会取消已有模拟挂单或干预持仓退出
- `scan` 只执行 `tick -> propose`，不会确认挂单或真实下单
- `status` 返回 `risk_summary`，包含单笔风险、日亏损余量、日亏损上限和控制状态
- 行情分析型 `propose/scan` 默认有 15 分钟草案冷却，可通过本地账本 `settings` 在 60-3600 秒内调整；CLI/API 可用 `force` 人工绕过，自动运行不绕过
- `tick` 对同一根 1 分钟 K 线幂等：重复点击只刷新权益，不重复成交或止盈止损
- 新挂单不会用创建所在 K 线的历史 high/low 乐观成交
- 草案和开放入场挂单过期后会自动失效
- 自动 tick 只在本地 paper server 进程内运行；服务关闭后自动停止
- 自动运行启动前会执行 preflight，自检失败时不得启动自动循环
- 自动运行 `scan` 模式只执行 `tick -> propose`，不会自动确认挂单
- 自动 tick 行情失败时只记录错误，不使用旧数据模拟交易
- 自动运行连续错误会熔断停止，阈值默认 3 次，可在启动自动运行时设置为 1-10 次
- CLI 和本地 Web server 使用同账本 `.lock` 文件串行化写入，降低同时操作同一 paper 账本时的数据覆盖风险
- 每次有效 tick 记录权益快照，`status` 返回最近权益快照、最近已平仓交易和绩效统计
- `/api/export/state` 只导出本地 paper 账本 JSON，不包含真实账户凭据
- `paper_server.py --state-path` 可隔离本地账本，自动 tick 和全部 API 使用同一路径

---

## Paul Wei 的交易风格

**理解他的风格，才能正确使用本 skill 的建议。**

他的方法与大多数散户直觉相反：

- **不追价**：所有建仓通过限价挂单完成，等价格来，不用市价单。建仓中位耗时 3.5 小时。
- **不能只依赖止损单**：止损单使用率 <1%，但核心前提是小仓位、明确结构失效条件和退出计划。单笔标准风险仅 0.5% 账户净值。
- **逆势思维**：MA30 偏低 >10% 时倾向建多抄底，偏高 >10% 时倾向减仓或做空波段。
- **接受低胜率**：方向段胜率仅 26.3%，但单次盈利远大于亏损（利润因子 6.87），依靠高不对称性盈利。
- **三维共振入场**：只有方向信号、结构信号、资金费率信号同时出现时才加大仓位。
- **分批出场**：动能减弱时开始减仓，历史平均在最大有利偏移的 84% 位置退出，不等最高点。

> 本 skill 生成的入场区和仓位计划，设计用于**限价挂单**，不是建议追价市价进场。

---

## 快速参考

| 参数 | 数值 |
|---|---|
| 单笔标准风险 | 0.5% 账户净值 |
| 单笔硬上限 | 3.0% 账户净值 |
| MA30 过热线 | > +10%（倾向减仓/做空） |
| MA30 超跌线 | < -10%（倾向加多/抄底） |
| 利润捕获目标 | ~84% MFE |
| 建仓中位时长 | 3.5 小时 |
| 止损单使用率 | < 1% |

---

## 数据来源

- 交易数据：[BTC-Trading-Since-2020](https://github.com/paulwei-coolish/BTC-Trading-Since-2020)（173,058 笔成交，2020–2026）
- 实时行情：并发竞速 MEXC（`contract.mexc.com`）、Bitget（`api.bitget.com`）、Binance USDT-M（`fapi.binance.com`）、OKX SWAP（`www.okx.com/api/v5`）、Bybit USDT linear（`api.bybit.com/v5`）公开 API；无需 API Key
- 实时账户看板：[wsnb.online](https://wsnb.online)

### 行情路由参数

默认请求客户端优先使用系统 `curl`，无 `curl` 时回退到 Python `urllib`。默认请求级超时为 `2.5s`，整体路由窗口为 `4.5s`，默认直连公共行情源以避免本机系统代理拖慢请求。可用环境变量调整：

```bash
PAULWEI_MARKET_REQUEST_TIMEOUT=2.0 PAULWEI_MARKET_ROUTE_TIMEOUT=4.0 python3 scripts/analyze.py BTCUSDT
```

如需限制数据源：

```bash
PAULWEI_MARKET_PROVIDERS=okx,bybit python3 scripts/analyze.py BTCUSDT
```

如需强制走系统代理或强制使用 `urllib`：

```bash
PAULWEI_MARKET_PROXY_MODE=system PAULWEI_MARKET_HTTP_CLIENT=urllib python3 scripts/analyze.py BTCUSDT
```

---

## 边界说明

- 本 skill **不执行实际交易**，仅提供教育性市场结构分析和风险校验
- Paper 机器人只写入本地 `data/paper_state.json` 模拟账本，不保存任何真实账户凭据
- 相对强弱（BTC/NASDAQ 比率）需用户在 TradingView 手动确认，本 skill 不获取 NASDAQ 数据
- MA30 ±10% 阈值基于 BTC 历史数据，用于其他币种为合理推断，非实证结论
- **方向判断由用户主导**，本 skill 提供结构信息和风险校验，不替代判断

---

*基于 Paul Wei (@coolish) 公开实盘档案逆向工程。不构成投资建议。*
