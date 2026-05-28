const els = {
  connectionStatus: document.querySelector("#connectionStatus"),
  nextStepTitle: document.querySelector("#nextStepTitle"),
  nextStepText: document.querySelector("#nextStepText"),
  dataStatusText: document.querySelector("#dataStatusText"),
  balanceInput: document.querySelector("#balanceInput"),
  riskInput: document.querySelector("#riskInput"),
  leverageInput: document.querySelector("#leverageInput"),
  initBtn: document.querySelector("#initBtn"),
  proposeBtn: document.querySelector("#proposeBtn"),
  placeBtn: document.querySelector("#placeBtn"),
  tickBtn: document.querySelector("#tickBtn"),
  cancelBtn: document.querySelector("#cancelBtn"),
  autoStartBtn: document.querySelector("#autoStartBtn"),
  autoStopBtn: document.querySelector("#autoStopBtn"),
  autoIntervalInput: document.querySelector("#autoIntervalInput"),
  autoStatusText: document.querySelector("#autoStatusText"),
  refreshBtn: document.querySelector("#refreshBtn"),
  clearLogBtn: document.querySelector("#clearLogBtn"),
  marketPriceValue: document.querySelector("#marketPriceValue"),
  marketChangeValue: document.querySelector("#marketChangeValue"),
  equityValue: document.querySelector("#equityValue"),
  dailyPnlValue: document.querySelector("#dailyPnlValue"),
  drawdownValue: document.querySelector("#drawdownValue"),
  riskValue: document.querySelector("#riskValue"),
  planBadge: document.querySelector("#planBadge"),
  tradeCountBadge: document.querySelector("#tradeCountBadge"),
  netPnlValue: document.querySelector("#netPnlValue"),
  realizedPnlValue: document.querySelector("#realizedPnlValue"),
  unrealizedPnlValue: document.querySelector("#unrealizedPnlValue"),
  winRateValue: document.querySelector("#winRateValue"),
  profitFactorValue: document.querySelector("#profitFactorValue"),
  currentDrawdownValue: document.querySelector("#currentDrawdownValue"),
  plansView: document.querySelector("#plansView"),
  positionsView: document.querySelector("#positionsView"),
  ordersView: document.querySelector("#ordersView"),
  tradesView: document.querySelector("#tradesView"),
  equitySnapshotsView: document.querySelector("#equitySnapshotsView"),
  logView: document.querySelector("#logView"),
};

let latestStatus = null;

function fmt(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return Number(value).toFixed(digits);
}

function log(label, payload) {
  const time = new Date().toLocaleTimeString();
  els.logView.textContent = `[${time}] ${label}\n${JSON.stringify(payload, null, 2)}\n\n` + els.logView.textContent;
}

async function api(path, body = null) {
  setBusy(true);
  try {
    const options = body
      ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
      : { method: "GET" };
    const response = await fetch(path, options);
    const payload = await response.json();
    if (!response.ok || payload.ok === false) throw new Error(payload.error || `HTTP ${response.status}`);
    els.connectionStatus.textContent = "已连接";
    return payload;
  } catch (error) {
    els.connectionStatus.textContent = "错误";
    log("错误", { message: error.message });
    throw error;
  } finally {
    setBusy(false);
  }
}

function setBusy(busy) {
  [
    els.initBtn,
    els.proposeBtn,
    els.placeBtn,
    els.tickBtn,
    els.cancelBtn,
    els.autoStartBtn,
    els.autoStopBtn,
    els.refreshBtn,
  ].forEach((button) => {
    button.disabled = busy;
  });
}

function fmtTime(value) {
  if (!value) return "--";
  if (typeof value === "number") return new Date(value).toLocaleTimeString();
  return String(value).replace("T", " ").replace("Z", " UTC");
}

function pnlClass(value) {
  const number = Number(value);
  if (number > 0) return "positive";
  if (number < 0) return "negative";
  return "";
}

function renderDataLine(status) {
  const statusMap = {
    live: "实时",
    stale: "滞后",
    unavailable: "不可用",
    unknown: "未知",
  };
  const marketText = statusMap[status.market_status] || status.market_status || "未知";
  const age = Number.isFinite(Number(status.market_age_seconds))
    ? `${fmt(status.market_age_seconds, 1)} 秒`
    : "--";
  const tickText = status.last_tick_at ? fmtTime(status.last_tick_at) : "尚未 tick";
  const actionMap = {
    processed: "已处理新 K 线",
    already_processed: "同一 K 线已跳过重复成交",
    placed: "已挂单",
    cancelled: "已取消",
    initialized: "已初始化",
  };
  const actionText = actionMap[status.last_action] || status.last_action || "无";
  const auto = status.auto_tick || {};
  const autoText = auto.running ? `自动运行中，每 ${fmt(auto.interval_seconds, 0)} 秒` : "自动未启动";
  els.dataStatusText.textContent = `行情状态：${marketText}，延迟 ${age}；上次 Tick：${tickText}；账本动作：${actionText}；${autoText}`;
}

function renderAutoStatus(autoTick) {
  const auto = autoTick || {};
  const runningText = auto.running ? "运行中" : "已停止";
  const intervalText = Number.isFinite(Number(auto.interval_seconds))
    ? `${fmt(auto.interval_seconds, 0)} 秒`
    : "--";
  const lastTickText = auto.last_tick_at ? fmtTime(auto.last_tick_at) : "尚未执行";
  const errorText = auto.last_error ? `；最近错误：${auto.last_error}` : "";
  els.autoStatusText.textContent = `${runningText} · 间隔 ${intervalText} · 成功 ${auto.tick_count || 0} 次 · 错误 ${auto.error_count || 0} 次 · 上次 ${lastTickText}${errorText}`;
}

function setNextStep(status) {
  const hasPlan = (status.pending_plans || []).length > 0;
  const hasOrders = (status.open_orders || []).length > 0;
  const hasPosition = Boolean(status.position);
  const firstOrder = status.open_orders?.[0];

  if (status.risk_locked) {
    els.nextStepTitle.textContent = "今天停止交易";
    els.nextStepText.textContent = "日内亏损达到风控线，先不要生成新草案。";
    return;
  }
  if (hasPosition || hasOrders) {
    els.nextStepTitle.textContent = "推进一次模拟";
    const distance = firstOrder?.distance_to_market_pct;
    const distanceText = Number.isFinite(Number(distance)) ? `第一档挂单距现价 ${fmt(distance, 2)}%。` : "";
    els.nextStepText.textContent = `点击“刷新行情并模拟成交”，检查挂单、止盈止损和权益变化。${distanceText}`;
    return;
  }
  if (hasPlan) {
    els.nextStepTitle.textContent = "确认或等待";
    els.nextStepText.textContent = "已有做空草案。确认后会变成模拟挂单；不确认就只作为观察。";
    return;
  }
  els.nextStepTitle.textContent = "生成草案";
  els.nextStepText.textContent = "点击“生成做空草案”，系统会用实时行情判断是否值得模拟做空。";
}

function renderStatus(status) {
  latestStatus = status;
  const market = status.market || {};
  els.marketPriceValue.textContent = market.price ? `${fmt(market.price, 1)}` : "--";
  els.marketChangeValue.textContent = Number.isFinite(Number(market.change_pct_24h))
    ? `${fmt(market.change_pct_24h, 2)}%`
    : "--";
  els.marketChangeValue.className = Number(market.change_pct_24h) < 0 ? "negative" : "positive";
  els.equityValue.textContent = `${fmt(status.equity)} U`;
  els.dailyPnlValue.textContent = `${fmt(status.daily_realized_pnl)} U`;
  els.dailyPnlValue.className = Number(status.daily_realized_pnl) < 0 ? "negative" : "positive";
  els.drawdownValue.textContent = `${fmt(status.max_drawdown_pct, 2)}%`;
  els.riskValue.textContent = status.risk_locked ? "锁定" : "正常";
  els.riskValue.className = status.risk_locked ? "warning" : "positive";
  renderDataLine(status);
  renderAutoStatus(status.auto_tick);
  setNextStep(status);

  const plans = status.pending_plans || [];
  els.planBadge.textContent = String(plans.length);
  els.plansView.className = plans.length ? "" : "empty";
  els.plansView.innerHTML = plans.length ? renderSimplePlan(plans[0]) : "暂无草案";

  els.positionsView.className = status.position ? "" : "empty";
  els.positionsView.innerHTML = status.position ? renderPosition(status.position) : "暂无持仓";
  els.ordersView.innerHTML = (status.open_orders || []).map(renderOrder).join("");
  renderPerformance(status.performance || {});
  renderTrades(status.closed_trades || []);
  renderEquitySnapshots(status.equity_snapshots || []);
}

function renderSimplePlan(plan) {
  const entries = (plan.entries || []).map((entry) => `${entry.price} / ${entry.contracts}张`).join("；");
  const tps = (plan.take_profits || []).map((tp) => fmt(tp.price, 1)).join(" / ");
  return `
    <article class="simple-card">
      <div class="headline-row">
        <strong>做空草案</strong>
        <span>${plan.plan_id}</span>
      </div>
      <div class="big-risk">最大模拟亏损 ${fmt(plan.max_loss_usdt, 2)} U</div>
      <div class="simple-list">
        <p><span>入场</span>${entries}</p>
        <p><span>止损</span>${fmt(plan.stop_loss, 1)}</p>
        <p><span>止盈</span>${tps}</p>
        <p><span>保证金</span>${fmt(plan.required_margin_usdt, 2)} U</p>
        <p><span>理由</span>${plan.reason}</p>
      </div>
    </article>
  `;
}

function renderPosition(position) {
  return `
    <article class="simple-card">
      <div class="headline-row">
        <strong>${position.side} 持仓</strong>
        <span>${position.position_id}</span>
      </div>
      <div class="simple-list">
        <p><span>均价</span>${fmt(position.entry_price, 1)}</p>
        <p><span>剩余</span>${position.remaining_contracts} 张</p>
        <p><span>止损</span>${fmt(position.stop_loss, 1)}</p>
        <p><span>已实现</span>${fmt(position.realized_pnl, 4)} U</p>
      </div>
    </article>
  `;
}

function renderOrder(order) {
  const distance = Number.isFinite(Number(order.distance_to_market_pct))
    ? `${fmt(order.distance_to_market_pct, 2)}%`
    : "--";
  return `
    <article class="order-line">
      <strong>${order.side}</strong>
      <span>${fmt(order.price, 1)}</span>
      <span>${order.contracts} 张</span>
      <span>距现价 ${distance}</span>
    </article>
  `;
}

function renderPerformance(performance) {
  els.tradeCountBadge.textContent = String(performance.trade_count || 0);
  els.netPnlValue.textContent = `${fmt(performance.net_pnl_usdt, 4)} U`;
  els.netPnlValue.className = pnlClass(performance.net_pnl_usdt);
  els.realizedPnlValue.textContent = `${fmt(performance.realized_pnl_usdt, 4)} U`;
  els.realizedPnlValue.className = pnlClass(performance.realized_pnl_usdt);
  els.unrealizedPnlValue.textContent = `${fmt(performance.unrealized_pnl_usdt, 4)} U`;
  els.unrealizedPnlValue.className = pnlClass(performance.unrealized_pnl_usdt);
  els.winRateValue.textContent = `${fmt(performance.win_rate_pct, 2)}%`;
  els.profitFactorValue.textContent = performance.profit_factor === null || performance.profit_factor === undefined
    ? "--"
    : fmt(performance.profit_factor, 2);
  els.currentDrawdownValue.textContent = `${fmt(performance.current_drawdown_pct, 2)}%`;
  els.currentDrawdownValue.className = Number(performance.current_drawdown_pct) > 0 ? "warning" : "";
}

function renderTrades(trades) {
  els.tradesView.className = trades.length ? "history-list" : "empty";
  els.tradesView.innerHTML = trades.length
    ? trades.slice().reverse().map((trade) => `
        <article class="history-line">
          <strong class="${pnlClass(trade.realized_pnl)}">${fmt(trade.realized_pnl, 4)} U</strong>
          <span>${trade.reason || "--"} · ${trade.contracts} 张 · ${fmt(trade.exit_price, 1)}</span>
          <small>${fmtTime(trade.closed_at)}</small>
        </article>
      `).join("")
    : "暂无已平仓交易";
}

function renderEquitySnapshots(snapshots) {
  els.equitySnapshotsView.className = snapshots.length ? "history-list" : "empty";
  els.equitySnapshotsView.innerHTML = snapshots.length
    ? snapshots.slice(-10).reverse().map((snapshot) => `
        <article class="history-line">
          <strong>${fmt(snapshot.equity, 4)} U</strong>
          <span>${snapshot.source || "tick"} · 标记价 ${fmt(snapshot.mark_price, 1)} · 未实现 ${fmt(snapshot.unrealized_pnl, 4)} U</span>
          <small>${fmtTime(snapshot.created_at)}</small>
        </article>
      `).join("")
    : "暂无 tick 快照";
}

async function refreshStatus(label = "状态") {
  const status = await api("/api/status");
  renderStatus(status);
  log(label, status);
}

els.initBtn.addEventListener("click", async () => {
  if (!confirm("会重置本地 paper 账本，确认继续？")) return;
  const payload = await api("/api/init", { balance: Number(els.balanceInput.value || 500) });
  log("初始化", payload);
  await refreshStatus("初始化后状态");
});

els.proposeBtn.addEventListener("click", async () => {
  const payload = await api("/api/propose", {
    symbol: "BTCUSDT",
    side: "short",
    risk_pct: Number(els.riskInput.value),
    leverage: Number(els.leverageInput.value),
  });
  log("生成草案", payload);
  await refreshStatus("草案后状态");
});

els.placeBtn.addEventListener("click", async () => {
  const plan = latestStatus?.pending_plans?.[0];
  if (!plan) {
    log("确认挂单", { ok: false, error: "没有待确认草案" });
    return;
  }
  const payload = await api("/api/place", { plan_id: plan.plan_id });
  log("确认挂单", payload);
  await refreshStatus("挂单后状态");
});

els.tickBtn.addEventListener("click", async () => {
  const payload = await api("/api/tick", {});
  log("Tick", payload);
  await refreshStatus("Tick 后状态");
});

els.cancelBtn.addEventListener("click", async () => {
  const hasPlan = latestStatus?.pending_plans?.length > 0;
  const hasOrders = latestStatus?.open_orders?.length > 0;
  if (!hasPlan && !hasOrders) {
    log("取消", { ok: false, error: "当前没有可取消的草案或挂单" });
    return;
  }
  if (!confirm("确认取消当前所有待确认草案和开放模拟挂单？")) return;
  const payload = await api("/api/cancel", { all: true });
  log("取消", payload);
  await refreshStatus("取消后状态");
});

els.autoStartBtn.addEventListener("click", async () => {
  const payload = await api("/api/auto/start", {
    interval_seconds: Number(els.autoIntervalInput.value || 60),
  });
  log("启动自动运行", payload);
  await refreshStatus("自动运行状态");
});

els.autoStopBtn.addEventListener("click", async () => {
  const payload = await api("/api/auto/stop", {});
  log("停止自动运行", payload);
  await refreshStatus("自动运行状态");
});

els.refreshBtn.addEventListener("click", () => refreshStatus());
els.clearLogBtn.addEventListener("click", () => {
  els.logView.textContent = "";
});

refreshStatus("启动状态").catch(() => {});
setInterval(() => {
  refreshStatus("自动刷新").catch(() => {});
}, 15000);
