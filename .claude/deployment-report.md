# paulwei-crypto-skill 部署报告

- 生成时间：2026-05-03 01:12（中国时区）
- 执行者：Codex分析AI
- 部署目标：`/Users/huangjiayang/.codex/skills/paulwei-crypto`
- 结论：已部署；当前网络环境下 Binance 返回 HTTP 451 时可自动切换到 OKX SWAP 公共实时行情

## 本次修复

- `scripts/analyze.py`
  - 增加 `^[A-Z0-9]{2,20}USDT$` symbol 白名单。
  - 使用 `urllib.parse.urlencode` 防止 query 参数污染。
  - 使用 Python 标准库 HTTP 客户端替代 `curl`。
  - 区分 HTTP 451、403、429、5xx 和交易对不存在。

- `SKILL.md`
  - 增加强制安全边界：非投资建议、不替用户决策、不执行实际交易。
  - 明确不连接交易账户、不请求 API Key、不生成下单代码。
  - 明确不得建议绕过地区、KYC、交易所或服务条款限制。
  - 行情失败时失败关闭，不使用旧数据或猜测继续制定策略。
  - 将 `curl/binance-cli` 从兜底数据源降级为脚本故障排查示例。
  - 增加 OKX SWAP 公共行情作为 Binance 受限或不可用时的合规备用源。

- `references/framework.md`
  - 删除 skill 外绝对路径。
  - 收紧“不依赖止损”相关措辞。

- `README.md`
  - 将“不依赖止损单”改为“不能只依赖止损单”，补充结构失效和退出计划。

## 验证

- `python3 -m py_compile scripts/analyze.py`：通过。
- `python3 -m json.tool evals/evals.json`：通过。
- 非法 symbol 测试：通过，`BTCUSDT&limit=1` 被拒绝。
- 有效 symbol 测试：通过；当前环境 Binance 返回 HTTP 451 后自动切换到 OKX SWAP，并输出完整指标。
- 安装后脚本测试：通过；非法 symbol 拒绝，BTCUSDT/SOLUSDT 可通过 OKX fallback 获取实时行情。

## 使用前提

需要重启 Codex 才能加载新安装的 skill。当前本机网络访问 Binance USDT-M 公共接口受限，但脚本已能自动使用 OKX SWAP 公共行情作为备用实时数据源。该 skill 只提供教育性市场结构分析与风险校验，不构成投资建议。
