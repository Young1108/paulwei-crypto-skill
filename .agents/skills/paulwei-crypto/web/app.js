const els = {
  connectionStatus: document.querySelector("#connectionStatus"),
  nextStepTitle: document.querySelector("#nextStepTitle"),
  nextStepText: document.querySelector("#nextStepText"),
  dataStatusText: document.querySelector("#dataStatusText"),
  balanceInput: document.querySelector("#balanceInput"),
  riskInput: document.querySelector("#riskInput"),
  leverageInput: document.querySelector("#leverageInput"),
  proposalCooldownInput: document.querySelector("#proposalCooldownInput"),
  saveSettingsBtn: document.querySelector("#saveSettingsBtn"),
  settingsStatusText: document.querySelector("#settingsStatusText"),
  initBtn: document.querySelector("#initBtn"),
  proposeBtn: document.querySelector("#proposeBtn"),
  scanBtn: document.querySelector("#scanBtn"),
  placeBtn: document.querySelector("#placeBtn"),
  tickBtn: document.querySelector("#tickBtn"),
  cancelBtn: document.querySelector("#cancelBtn"),
  pauseBtn: document.querySelector("#pauseBtn"),
  resumeBtn: document.querySelector("#resumeBtn"),
  pauseStatusText: document.querySelector("#pauseStatusText"),
  preflightBtn: document.querySelector("#preflightBtn"),
  preflightStatusText: document.querySelector("#preflightStatusText"),
  preflightChecksView: document.querySelector("#preflightChecksView"),
  autoStartBtn: document.querySelector("#autoStartBtn"),
  autoStopBtn: document.querySelector("#autoStopBtn"),
  autoModeInput: document.querySelector("#autoModeInput"),
  autoIntervalInput: document.querySelector("#autoIntervalInput"),
  autoMaxErrorInput: document.querySelector("#autoMaxErrorInput"),
  autoStatusText: document.querySelector("#autoStatusText"),
  autoResetBtn: document.querySelector("#autoResetBtn"),
  refreshBtn: document.querySelector("#refreshBtn"),
  exportStateBtn: document.querySelector("#exportStateBtn"),
  backupRefreshBtn: document.querySelector("#backupRefreshBtn"),
  backupCountBadge: document.querySelector("#backupCountBadge"),
  backupsView: document.querySelector("#backupsView"),
  clearLogBtn: document.querySelector("#clearLogBtn"),
  marketPriceValue: document.querySelector("#marketPriceValue"),
  marketChangeValue: document.querySelector("#marketChangeValue"),
  equityValue: document.querySelector("#equityValue"),
  dailyPnlValue: document.querySelector("#dailyPnlValue"),
  drawdownValue: document.querySelector("#drawdownValue"),
  riskValue: document.querySelector("#riskValue"),
  planBadge: document.querySelector("#planBadge"),
  tradeCountBadge: document.querySelector("#tradeCountBadge"),
  riskEventBadge: document.querySelector("#riskEventBadge"),
  standardRiskValue: document.querySelector("#standardRiskValue"),
  maxRiskCapValue: document.querySelector("#maxRiskCapValue"),
  dailyRiskRemainingValue: document.querySelector("#dailyRiskRemainingValue"),
  dailyRiskLimitValue: document.querySelector("#dailyRiskLimitValue"),
  maxLeverageValue: document.querySelector("#maxLeverageValue"),
  controlStateValue: document.querySelector("#controlStateValue"),
  proposalCooldownValue: document.querySelector("#proposalCooldownValue"),
  lastProposalValue: document.querySelector("#lastProposalValue"),
  netPnlValue: document.querySelector("#netPnlValue"),
  realizedPnlValue: document.querySelector("#realizedPnlValue"),
  unrealizedPnlValue: document.querySelector("#unrealizedPnlValue"),
  winRateValue: document.querySelector("#winRateValue"),
  profitFactorValue: document.querySelector("#profitFactorValue"),
  currentDrawdownValue: document.querySelector("#currentDrawdownValue"),
  plansView: document.querySelector("#plansView"),
  positionsView: document.querySelector("#positionsView"),
  ordersView: document.querySelector("#ordersView"),
  riskEventsView: document.querySelector("#riskEventsView"),
  tradesView: document.querySelector("#tradesView"),
  equitySnapshotsView: document.querySelector("#equitySnapshotsView"),
  equityCurveCanvas: document.querySelector("#equityCurveCanvas"),
  equityCurveText: document.querySelector("#equityCurveText"),
  logView: document.querySelector("#logView"),
};

let latestStatus = null;

function fmt(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return Number(value).toFixed(digits);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  }[char]));
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
    els.scanBtn,
    els.placeBtn,
    els.tickBtn,
    els.cancelBtn,
    els.pauseBtn,
    els.resumeBtn,
    els.preflightBtn,
    els.autoStartBtn,
    els.autoStopBtn,
    els.autoResetBtn,
    els.saveSettingsBtn,
    els.refreshBtn,
    els.exportStateBtn,
    els.backupRefreshBtn,
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
    paused: "已暂停新草案",
    resumed: "已恢复新草案",
  };
  const actionText = actionMap[status.last_action] || status.last_action || "无";
  const auto = status.auto_tick || {};
  const autoMode = auto.mode === "scan" ? "Scan" : "Tick";
  const autoText = auto.halted_at
    ? `自动已熔断，${autoMode}`
    : (auto.running ? `自动运行中，${autoMode}，每 ${fmt(auto.interval_seconds, 0)} 秒` : "自动未启动");
  els.dataStatusText.textContent = `行情状态：${marketText}，延迟 ${age}；上次 Tick：${tickText}；账本动作：${actionText}；${autoText}`;
}

function renderPauseStatus(status) {
  if (status.trading_paused) {
    const reason = status.pause_reason ? ` · ${status.pause_reason}` : "";
    els.pauseStatusText.textContent = `已暂停${reason}`;
    els.pauseStatusText.className = "warning";
    return;
  }
  els.pauseStatusText.textContent = "可生成";
  els.pauseStatusText.className = "positive";
}

function renderAutoStatus(autoTick) {
  const auto = autoTick || {};
  if (document.activeElement !== els.autoMaxErrorInput && auto.max_consecutive_errors) {
    els.autoMaxErrorInput.value = String(auto.max_consecutive_errors);
  }
  const runningText = auto.halted_at ? "已熔断" : (auto.running ? "运行中" : "已停止");
  const modeText = auto.mode === "scan" ? "Scan" : "Tick";
  const intervalText = Number.isFinite(Number(auto.interval_seconds))
    ? `${fmt(auto.interval_seconds, 0)} 秒`
    : "--";
  const lastTickText = auto.last_tick_at ? fmtTime(auto.last_tick_at) : "尚未执行";
  const consecutiveText = `连续错误 ${auto.consecutive_error_count || 0}/${auto.max_consecutive_errors || 3}`;
  const errorText = auto.last_error ? `；最近错误：${auto.last_error}` : "";
  const haltText = auto.halt_reason ? `；熔断：${auto.halt_reason}` : "";
  els.autoStatusText.textContent = `${runningText} · ${modeText} · 间隔 ${intervalText} · 成功 ${auto.tick_count || 0} 次 · 错误 ${auto.error_count || 0} 次 · ${consecutiveText} · 上次 ${lastTickText}${errorText}${haltText}`;
  els.autoStatusText.className = auto.halted_at ? "warning" : "";
}

function renderPreflight(payload) {
  const status = payload.status || "unknown";
  const statusText = {
    pass: "自检通过",
    warn: "自检有警告",
    fail: "自检失败",
  }[status] || "自检未知";
  const failed = (payload.checks || []).filter((check) => check.status === "fail").length;
  const warned = (payload.checks || []).filter((check) => check.status === "warn").length;
  els.preflightStatusText.textContent = `${statusText} · 失败 ${failed} · 警告 ${warned}`;
  els.preflightStatusText.className = status === "fail" ? "negative" : (status === "warn" ? "warning" : "positive");
  renderPreflightChecks(payload.checks || []);
}

function renderPreflightChecks(checks) {
  const labelMap = {
    pass: "通过",
    warn: "警告",
    fail: "失败",
    skip: "跳过",
  };
  els.preflightChecksView.className = checks.length ? "preflight-checks" : "preflight-checks empty";
  els.preflightChecksView.innerHTML = checks.length
    ? checks.map((check) => {
        const details = Object.keys(check.details || {}).length
          ? `<small class="details">${escapeHtml(JSON.stringify(check.details))}</small>`
          : "";
        const remediation = check.remediation
          ? `<small class="remediation">处理建议：${escapeHtml(check.remediation)}</small>`
          : "";
        return `
          <article class="preflight-check ${escapeHtml(check.status || "skip")}">
            <strong>${escapeHtml(labelMap[check.status] || check.status || "--")}</strong>
            <span>${escapeHtml(check.name || "--")} · ${escapeHtml(check.message || "--")}</span>
            ${remediation}
            ${details}
          </article>
        `;
      }).join("")
    : "尚未运行自检";
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
  if (status.trading_paused) {
    els.nextStepTitle.textContent = "新草案已暂停";
    els.nextStepText.textContent = "暂停期间不生成新草案；已有模拟挂单和持仓仍可继续 tick。";
    return;
  }
  if (status.proposal_control?.cooldown_remaining_seconds > 0 && !hasPosition && !hasOrders && !hasPlan) {
    const minutes = Math.ceil(status.proposal_control.cooldown_remaining_seconds / 60);
    els.nextStepTitle.textContent = "等待冷却";
    els.nextStepText.textContent = `草案生成冷却剩余约 ${minutes} 分钟，避免重复请求行情分析。`;
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
  if (document.activeElement !== els.proposalCooldownInput && status.proposal_control?.cooldown_seconds) {
    els.proposalCooldownInput.value = String(status.proposal_control.cooldown_seconds);
    els.settingsStatusText.textContent = "设置已同步";
  }
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
  els.riskValue.textContent = status.risk_locked ? "锁定" : (status.trading_paused ? "暂停" : "正常");
  els.riskValue.className = status.risk_locked || status.trading_paused ? "warning" : "positive";
  renderDataLine(status);
  renderPauseStatus(status);
  renderAutoStatus(status.auto_tick);
  renderRiskSummary(status.risk_summary || {}, status.risk_events || [], status.proposal_control || {});
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
  renderEquityCurve(status.equity_snapshots || []);
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

function renderRiskSummary(riskSummary, riskEvents, proposalControl) {
  els.riskEventBadge.textContent = String(riskEvents.length || 0);
  els.standardRiskValue.textContent = `${fmt(riskSummary.standard_risk_usdt, 2)} U`;
  els.maxRiskCapValue.textContent = `${fmt(riskSummary.max_risk_usdt, 2)} U`;
  els.dailyRiskRemainingValue.textContent = `${fmt(riskSummary.daily_loss_remaining_usdt, 2)} U`;
  els.dailyRiskRemainingValue.className = Number(riskSummary.daily_loss_remaining_usdt) <= 0 ? "warning" : "positive";
  els.dailyRiskLimitValue.textContent = `${fmt(riskSummary.daily_loss_limit_usdt, 2)} U`;
  els.maxLeverageValue.textContent = `${fmt(riskSummary.max_leverage, 0)}x`;
  const controlText = riskSummary.risk_locked
    ? "日损锁定"
    : (riskSummary.trading_paused ? "手动暂停" : "运行");
  els.controlStateValue.textContent = controlText;
  els.controlStateValue.className = riskSummary.risk_locked || riskSummary.trading_paused ? "warning" : "positive";
  const cooldownRemaining = Number(proposalControl.cooldown_remaining_seconds || 0);
  els.proposalCooldownValue.textContent = cooldownRemaining > 0
    ? `${Math.ceil(cooldownRemaining / 60)} 分钟`
    : "可生成";
  els.proposalCooldownValue.className = cooldownRemaining > 0 ? "warning" : "positive";
  els.lastProposalValue.textContent = proposalControl.last_proposal_status || "--";
  els.lastProposalValue.className = proposalControl.last_proposal_status === "cooldown" ? "warning" : "";
  renderRiskEvents(riskEvents);
}

function renderRiskEvents(events) {
  els.riskEventsView.className = events.length ? "history-list" : "empty";
  els.riskEventsView.innerHTML = events.length
    ? events.slice().reverse().map((event) => `
        <article class="history-line">
          <strong>${event.event_type || "--"}</strong>
          <span>${event.reason || "--"}</span>
          <small>${fmtTime(event.created_at)}</small>
        </article>
      `).join("")
    : "暂无风控事件";
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

function renderBackups(payload) {
  const backups = payload.backups || [];
  els.backupCountBadge.textContent = String(backups.length);
  els.backupsView.className = backups.length ? "history-list" : "empty";
  els.backupsView.innerHTML = backups.length
    ? backups.slice(0, 10).map((backup) => `
        <article class="history-line">
          <strong>${backup.name || "--"}</strong>
          <span>${fmt(Number(backup.size_bytes) / 1024, 2)} KB · 保留上限 ${payload.retention_count || "--"} 个</span>
          <small>${fmtTime(backup.modified_at)}</small>
        </article>
      `).join("")
    : "暂无账本备份";
}

function renderEquityCurve(snapshots) {
  const canvas = els.equityCurveCanvas;
  const context = canvas.getContext("2d");
  const width = canvas.clientWidth || canvas.width;
  const height = canvas.clientHeight || canvas.height;
  const scale = window.devicePixelRatio || 1;
  if (canvas.width !== Math.floor(width * scale) || canvas.height !== Math.floor(height * scale)) {
    canvas.width = Math.floor(width * scale);
    canvas.height = Math.floor(height * scale);
  }
  context.setTransform(scale, 0, 0, scale, 0, 0);
  context.clearRect(0, 0, width, height);

  const points = snapshots
    .map((snapshot) => ({
      equity: Number(snapshot.equity),
      time: snapshot.created_at,
    }))
    .filter((point) => Number.isFinite(point.equity));

  context.fillStyle = "#20262b";
  context.fillRect(0, 0, width, height);

  if (points.length < 2) {
    els.equityCurveText.textContent = points.length === 1
      ? `仅 1 个快照：${fmt(points[0].equity, 4)} U`
      : "暂无权益快照";
    context.fillStyle = "#9aa7b1";
    context.font = "13px system-ui, sans-serif";
    context.fillText("需要至少 2 个 tick 快照生成曲线", 18, Math.round(height / 2));
    return;
  }

  const padding = { top: 18, right: 18, bottom: 30, left: 58 };
  const chartWidth = Math.max(1, width - padding.left - padding.right);
  const chartHeight = Math.max(1, height - padding.top - padding.bottom);
  const values = points.map((point) => point.equity);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const range = maxValue - minValue || Math.max(1, Math.abs(maxValue) * 0.01);
  const lower = minValue - range * 0.08;
  const upper = maxValue + range * 0.08;
  const yFor = (value) => padding.top + (upper - value) / (upper - lower) * chartHeight;
  const xFor = (index) => padding.left + index / (points.length - 1) * chartWidth;

  context.strokeStyle = "#2d353c";
  context.lineWidth = 1;
  context.beginPath();
  for (let i = 0; i <= 4; i += 1) {
    const y = padding.top + (chartHeight / 4) * i;
    context.moveTo(padding.left, y);
    context.lineTo(width - padding.right, y);
  }
  context.stroke();

  context.fillStyle = "#9aa7b1";
  context.font = "12px system-ui, sans-serif";
  context.fillText(`${fmt(upper, 2)} U`, 10, padding.top + 4);
  context.fillText(`${fmt(lower, 2)} U`, 10, height - padding.bottom + 4);

  const startEquity = points[0].equity;
  const endEquity = points[points.length - 1].equity;
  const lineColor = endEquity >= startEquity ? "#45c47a" : "#ff6b6b";
  const gradient = context.createLinearGradient(0, padding.top, 0, height - padding.bottom);
  gradient.addColorStop(0, `${lineColor}44`);
  gradient.addColorStop(1, `${lineColor}05`);

  context.beginPath();
  points.forEach((point, index) => {
    const x = xFor(index);
    const y = yFor(point.equity);
    if (index === 0) context.moveTo(x, y);
    else context.lineTo(x, y);
  });
  context.strokeStyle = lineColor;
  context.lineWidth = 2;
  context.stroke();

  context.lineTo(width - padding.right, height - padding.bottom);
  context.lineTo(padding.left, height - padding.bottom);
  context.closePath();
  context.fillStyle = gradient;
  context.fill();

  context.fillStyle = lineColor;
  const lastX = xFor(points.length - 1);
  const lastY = yFor(endEquity);
  context.beginPath();
  context.arc(lastX, lastY, 4, 0, Math.PI * 2);
  context.fill();

  const change = endEquity - startEquity;
  els.equityCurveText.textContent = `${points.length} 个快照 · ${fmt(startEquity, 4)} U → ${fmt(endEquity, 4)} U · ${change >= 0 ? "+" : ""}${fmt(change, 4)} U`;
}

async function refreshStatus(label = "状态") {
  const status = await api("/api/status");
  renderStatus(status);
  log(label, status);
}

async function refreshBackups(label = "备份列表") {
  const payload = await api("/api/backups");
  renderBackups(payload);
  log(label, payload);
}

els.initBtn.addEventListener("click", async () => {
  if (!confirm("会重置本地 paper 账本，确认继续？")) return;
  const payload = await api("/api/init", { balance: Number(els.balanceInput.value || 500) });
  log("初始化", payload);
  await refreshStatus("初始化后状态");
  await refreshBackups("初始化后备份");
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

els.scanBtn.addEventListener("click", async () => {
  const payload = await api("/api/scan", {
    symbol: "BTCUSDT",
    side: "short",
    risk_pct: Number(els.riskInput.value),
    leverage: Number(els.leverageInput.value),
  });
  log("扫描一次", payload);
  await refreshStatus("扫描后状态");
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

els.pauseBtn.addEventListener("click", async () => {
  const payload = await api("/api/pause", { reason: "manual_pause_from_ui" });
  log("暂停新草案", payload);
  await refreshStatus("暂停后状态");
});

els.resumeBtn.addEventListener("click", async () => {
  const payload = await api("/api/resume", { reason: "manual_resume_from_ui" });
  log("恢复新草案", payload);
  await refreshStatus("恢复后状态");
});

els.preflightBtn.addEventListener("click", async () => {
  const payload = await api("/api/preflight", {
    mode: els.autoModeInput.value || "tick",
  });
  renderPreflight(payload);
  log("运行前自检", payload);
});

els.autoStartBtn.addEventListener("click", async () => {
  const payload = await api("/api/auto/start", {
    mode: els.autoModeInput.value || "tick",
    interval_seconds: Number(els.autoIntervalInput.value || 60),
    max_consecutive_errors: Number(els.autoMaxErrorInput.value || 3),
    symbol: "BTCUSDT",
    side: "short",
    risk_pct: Number(els.riskInput.value),
    leverage: Number(els.leverageInput.value),
  });
  if (payload.preflight) renderPreflight(payload.preflight);
  log("启动自动运行", payload);
  await refreshStatus("自动运行状态");
});

els.autoStopBtn.addEventListener("click", async () => {
  const payload = await api("/api/auto/stop", {});
  log("停止自动运行", payload);
  await refreshStatus("自动运行状态");
});

els.autoResetBtn.addEventListener("click", async () => {
  const payload = await api("/api/auto/reset", {});
  log("重置自动熔断", payload);
  await refreshStatus("重置后状态");
});

els.saveSettingsBtn.addEventListener("click", async () => {
  const payload = await api("/api/settings", {
    proposal_cooldown_seconds: Number(els.proposalCooldownInput.value || 900),
  });
  els.settingsStatusText.textContent = payload.updated ? "设置已保存" : "设置未变化";
  log("保存设置", payload);
  await refreshStatus("设置后状态");
});

els.refreshBtn.addEventListener("click", () => refreshStatus());
els.backupRefreshBtn.addEventListener("click", () => refreshBackups());
els.exportStateBtn.addEventListener("click", async () => {
  const payload = await api("/api/export/state");
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  anchor.href = url;
  anchor.download = `paper_state_export_${timestamp}.json`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
  log("导出账本", { ok: true, generated_at: payload.generated_at, snapshots: payload.ledger?.equity_snapshots?.length || 0 });
});
els.clearLogBtn.addEventListener("click", () => {
  els.logView.textContent = "";
});

refreshStatus("启动状态").catch(() => {});
refreshBackups("启动备份列表").catch(() => {});
window.addEventListener("resize", () => {
  if (latestStatus) renderEquityCurve(latestStatus.equity_snapshots || []);
});
setInterval(() => {
  refreshStatus("自动刷新").catch(() => {});
}, 15000);
