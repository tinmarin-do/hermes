"use strict";

let waterfallChart = null;

async function loadSnapshot() {
  const res = await fetch("/api/snapshot");
  if (!res.ok) return null;
  return res.json();
}

function fmtUsd(x) { return "$" + Number(x).toFixed(4); }
function fmtPct(x) { return (Number(x) * 100).toFixed(1) + "%"; }
function badge(dir) {
  const cls = dir === "BUY" ? "buy" : dir === "SELL" ? "sell" : "hold";
  return `<span class="badge ${cls}">${dir || "?"}</span>`;
}

let equityChart = null;

function renderPortfolio(pf) {
  const summary = document.getElementById("pf-summary");
  const tbody = document.querySelector("#portfolio tbody");
  document.getElementById("pf-mode").textContent = pf && pf.mode ? `(${pf.mode})` : "";
  if (!pf || !pf.available) {
    summary.innerHTML = "<span class='muted'>Sin datos de cartera.</span>";
    return;
  }
  summary.innerHTML =
    `<span class="big">${fmtUsd(pf.equity_usd)}</span><span class="muted small">equity</span>` +
    `<span class="prob">${fmtUsd(pf.balance_usd)}</span><span class="muted small">cash (${fmtPct(pf.cash_weight)})</span>` +
    `<span class="muted small">budget ${fmtUsd(pf.budget_usd)}</span>`;
  tbody.innerHTML = "";
  for (const r of pf.rows || []) {
    const champ = (pf.champion_now || {})[r.symbol] || {};
    const votes = champ.momentum
      ? Object.entries(champ.momentum)
          .map(([k, v]) => `<span class="${v >= 0 ? "pos" : "neg"}" title="${k}=${Number(v).toFixed(4)}">${v >= 0 ? "▲" : "▼"}</span>`)
          .join("")
      : "";
    const upnl = r.unrealized_pnl ?? 0, rpnl = r.realized_pnl ?? 0;
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${r.symbol} <span class="votes">${votes}</span></td>` +
      `<td>${r.side === "—" ? "<span class='muted'>—</span>" : badge(r.side)}</td>` +
      `<td>${fmtPct(r.weight)}</td>` +
      `<td>${r.target_weight == null ? "<span class='muted'>·</span>" : fmtPct(r.target_weight)}</td>` +
      `<td class="${upnl >= 0 ? "pos" : "neg"}">${fmtUsd(upnl)}</td>` +
      `<td class="${rpnl >= 0 ? "pos" : "neg"}">${fmtUsd(rpnl)}</td>`;
    tbody.appendChild(tr);
  }
  if (!(pf.rows || []).length)
    tbody.innerHTML = "<tr><td colspan='6' class='muted'>Todo en cash — día 0 del track record.</td></tr>";
  document.getElementById("pf-note").textContent =
    (pf.note || "") + " · ▲▼ = votos de momentum 7/14/30/90d del champion";
}

function renderEquity(eq) {
  const note = document.getElementById("equity-note");
  const metricsEl = document.getElementById("equity-metrics");
  if (!eq || !eq.available) {
    note.textContent = "Sin curva de equity todavía.";
    return;
  }
  const pts = eq.series || [];
  if (equityChart) equityChart.destroy();
  equityChart = new Chart(document.getElementById("equity-chart"), {
    type: "line",
    data: {
      labels: pts.map(p => p.ts.slice(0, 16)),
      datasets: [{ data: pts.map(p => p.equity), borderColor: "#60a5fa",
                   backgroundColor: "rgba(96,165,250,.15)", fill: true, tension: 0.2, pointRadius: 2 }],
    },
    options: { responsive: true, maintainAspectRatio: false,
               plugins: { legend: { display: false } },
               scales: { y: { title: { display: true, text: "equity (USD)" } } } },
  });
  const m = eq.metrics;
  metricsEl.innerHTML = m
    ? `<span class="metric">ret total <b class="${(m.total_return ?? 0) >= 0 ? "pos" : "neg"}">${fmtPct(m.total_return ?? 0)}</b></span>` +
      `<span class="metric">maxDD <b class="neg">${fmtPct(m.max_drawdown ?? 0)}</b></span>` +
      (m.sharpe != null ? `<span class="metric">Sharpe <b>${m.sharpe}</b></span>` : "") +
      (m.psr != null ? `<span class="metric">PSR <b>${m.psr}</b></span>` : "") +
      `<span class="metric muted">n=${m.n_points}</span>`
    : "";
  note.textContent = eq.note || "";
}

function renderSignals(sig) {
  const tbody = document.querySelector("#signals tbody");
  const hist = document.getElementById("signals-history");
  if (!sig || !sig.available || !(sig.rows || []).length) {
    tbody.innerHTML = "<tr><td colspan='4' class='muted'>Sin corridas comparables todavía — el signal log crece con cada corrida.</td></tr>";
    hist.textContent = "";
    return;
  }
  tbody.innerHTML = "";
  for (const r of sig.rows) {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${r.symbol}</td>` +
      `<td>${badge(r.champion.direction)} <span class="muted small">conf ${(r.champion.confidence ?? 0).toFixed(2)}</span></td>` +
      `<td>${badge(r.shadow.direction)} <span class="muted small">P=${(r.shadow.probability ?? 0.5).toFixed(3)}</span></td>` +
      `<td>${r.agree ? "🤝" : "⚡ divergen"}</td>`;
    tbody.appendChild(tr);
  }
  const h = (sig.history || []).map(x => `${x.model}: ${x.runs} corridas`).join(" · ");
  hist.textContent = `${sig.note || ""} · shadow=${sig.shadow_model || "?"} (run ${sig.shadow_run || "?"}) · ${h}`;
}

function renderDebate(d) {
  const summary = document.getElementById("debate-summary");
  const body = document.getElementById("debate-body");
  if (!d || !d.available) {
    summary.innerHTML = `<span class="muted">${(d && d.reason) || "Sin corridas persistidas."}</span>`;
    return;
  }
  summary.innerHTML =
    badge(d.debate_verdict) +
    `<span class="prob">conf ${((d.debate_confidence ?? 0) * 100).toFixed(0)}%</span>` +
    `<span>${d.risk_approved ? "✅ riesgo aprobado" : "❌ riesgo rechazado"}</span>` +
    `<span class="muted small">run ${(d.run_id || "").slice(0, 8)} · ${d.ts || ""}</span>`;
  const t = d.transcript || {};
  const rounds = (t.debate_rounds || [])
    .map((r, i) => `<details><summary>Ronda ${i + 1}</summary><pre>${JSON.stringify(r, null, 2)}</pre></details>`)
    .join("");
  body.innerHTML =
    `<details open><summary>PM — decisión final (${d.pm_action || "?"})</summary><pre>${d.pm_rationale || ""}</pre></details>` +
    `<details><summary>🐂 Tesis alcista</summary><pre>${t.bull_argument || "—"}</pre></details>` +
    `<details><summary>🐻 Tesis bajista</summary><pre>${t.bear_argument || "—"}</pre></details>` +
    `<details><summary>Síntesis de riesgo</summary><pre>${t.risk_synthesis || "—"}</pre></details>` +
    rounds;
}

function renderSymbolSelect(shap) {
  const sel = document.getElementById("symbol-select");
  sel.innerHTML = "";
  const symbols = Object.keys(shap.symbols || {});
  for (const s of symbols) {
    const opt = document.createElement("option");
    opt.value = s; opt.textContent = s;
    sel.appendChild(opt);
  }
  return symbols;
}

function renderPrediction(entry) {
  const p = entry.explanation.prediction || {};
  const dirClass = p.direction === "BUY" ? "buy" : p.direction === "SELL" ? "sell" : "hold";
  document.getElementById("prediction").innerHTML =
    `<span class="badge ${dirClass}">${p.direction || "?"}</span>` +
    `<span class="prob">P(↑) = ${(p.probability ?? 0).toFixed(3)}</span>` +
    `<span class="muted">confianza ${(p.confidence ?? 0).toFixed(2)} · régimen ${entry.regime || "?"}</span>`;
}

// Build a floating-bar waterfall: base_value → +/- each contribution → margin.
function renderWaterfall(entry) {
  const exp = entry.explanation;
  const base = exp.base_value ?? 0;
  const steps = exp.waterfall || [];

  const labels = ["base", ...steps.map(s => s.label)];
  const bars = [];           // [start, end] floating bars
  const colors = [];
  let running = base;

  bars.push([0, base]);
  colors.push("#6b7280");    // base — gray
  for (const s of steps) {
    const start = running;
    running += s.value;
    bars.push([start, running]);
    colors.push(s.value >= 0 ? "#16a34a" : "#dc2626");  // green up / red down
  }

  const data = {
    labels,
    datasets: [{
      data: bars,
      backgroundColor: colors,
      borderWidth: 0,
    }],
  };
  const opts = {
    indexAxis: "y",
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          label: (ctx) => {
            const i = ctx.dataIndex;
            if (i === 0) return "base = " + base.toFixed(4);
            const v = steps[i - 1].value;
            return (v >= 0 ? "+" : "") + v.toFixed(4) + " (log-odds)";
          },
        },
      },
    },
    scales: { x: { title: { display: true, text: "contribución a la predicción (log-odds)" } } },
  };

  if (waterfallChart) waterfallChart.destroy();
  waterfallChart = new Chart(document.getElementById("waterfall"), { type: "bar", data, options: opts });
}

function renderFeatures(entry) {
  const tbody = document.querySelector("#features tbody");
  tbody.innerHTML = "";
  for (const f of entry.explanation.top_features || []) {
    const tr = document.createElement("tr");
    const cls = f.shap_value >= 0 ? "pos" : "neg";
    tr.innerHTML = `<td>${f.feature}</td><td>${Number(f.feature_value).toFixed(4)}</td>` +
                   `<td class="${cls}">${f.shap_value >= 0 ? "+" : ""}${Number(f.shap_value).toFixed(4)}</td>`;
    tbody.appendChild(tr);
  }
}

function renderCost(cost) {
  if (!cost || !cost.available) {
    document.getElementById("cost-summary").innerHTML = "<span class='muted'>Sin datos de costo.</span>";
    return;
  }
  const pct = cost.budget_usd ? (cost.total_usd / cost.budget_usd * 100) : 0;
  document.getElementById("cost-summary").innerHTML =
    `<div class="big">${fmtUsd(cost.total_usd)} <span class="muted">/ $${cost.budget_usd}/mes (${pct.toFixed(2)}%)</span></div>` +
    `<div class="muted small">${cost.runs} corridas · ${cost.unlogged_runs} sin registrar en ledger</div>`;
  const tbody = document.querySelector("#cost-runs tbody");
  tbody.innerHTML = "";
  for (const r of cost.recent || []) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${r.run_id}</td><td>${r.tokens.toLocaleString()}</td>` +
                   `<td>${fmtUsd(r.cost_usd)}</td><td>${r.logged ? "✅" : "⏳"}</td>`;
    tbody.appendChild(tr);
  }
}

function renderPositions(pos) {
  document.getElementById("pos-mode").textContent = pos && pos.mode ? `(${pos.mode})` : "";
  if (!pos || !pos.available) {
    document.getElementById("pos-summary").innerHTML = "<span class='muted'>Sin datos de posiciones.</span>";
    return;
  }
  document.getElementById("pos-summary").innerHTML =
    `<div class="big">${fmtUsd(pos.balance_usd)} <span class="muted small">balance</span></div>`;
  const tbody = document.querySelector("#positions tbody");
  tbody.innerHTML = "";
  for (const p of pos.open || []) {
    const tr = document.createElement("tr");
    const cls = (p.unrealized_pnl ?? 0) >= 0 ? "pos" : "neg";
    tr.innerHTML = `<td>${p.symbol}</td><td>${p.action}</td><td>${p.quantity}</td>` +
                   `<td>${p.entry_price}</td><td class="${cls}">${(p.unrealized_pnl ?? 0).toFixed(2)}</td>`;
    tbody.appendChild(tr);
  }
  if (!(pos.open || []).length) tbody.innerHTML = "<tr><td colspan='5' class='muted'>Sin posiciones abiertas.</td></tr>";
}

let liveChart = null;

function renderLiveChart(officialSeries, live) {
  // La GRÁFICA de performance: curva oficial (1 punto/día, §8.9) + el punto
  // vivo "ahora" al final — cada ↻ mueve el último punto al instante actual.
  const canvas = document.getElementById("live-chart");
  if (!canvas || typeof Chart === "undefined") return;
  const pts = (officialSeries || []).map(p => ({ ts: p.ts.slice(0, 16), eq: p.equity }));
  pts.push({ ts: "ahora", eq: live.equity_usd });
  const up = pts.length < 2 || pts[pts.length - 1].eq >= pts[0].eq;
  const color = up ? "#34d399" : "#f87171";
  if (liveChart) liveChart.destroy();
  liveChart = new Chart(canvas, {
    type: "line",
    data: {
      labels: pts.map(p => p.ts),
      datasets: [{
        data: pts.map(p => p.eq), borderColor: color,
        backgroundColor: up ? "rgba(52,211,153,.12)" : "rgba(248,113,113,.12)",
        fill: true, tension: 0.2,
        pointRadius: pts.map((_, i) => (i === pts.length - 1 ? 5 : 2)),
      }],
    },
    options: { responsive: true, maintainAspectRatio: false,
               plugins: { legend: { display: false } },
               scales: { y: { title: { display: true, text: "equity (USD)" } } } },
  });
}

async function renderLive(officialSeries) {
  const summary = document.getElementById("live-summary");
  const tbody = document.querySelector("#live-positions tbody");
  const note = document.getElementById("live-note");
  summary.innerHTML = "<span class='muted'>Consultando Bitso…</span>";
  let live;
  try {
    const r = await fetch("/api/live");
    if (!r.ok) throw new Error((await r.json()).detail || r.status);
    live = await r.json();
  } catch (e) {
    summary.innerHTML = `<span class='muted'>En vivo no disponible: ${e.message}</span>`;
    return;
  }
  let deltaHtml = "";
  if (live.vs_snapshot) {
    const d = live.vs_snapshot;
    const cls = d.delta_usd >= 0 ? "pos" : "neg";
    const sign = d.delta_usd >= 0 ? "+" : "";
    deltaHtml =
      `<span class="prob ${cls}">${sign}${fmtUsd(d.delta_usd)} (${sign}${fmtPct(d.delta_pct)})</span>` +
      `<span class="muted small">desde el snapshot oficial</span>`;
  }
  summary.innerHTML =
    `<span class="big">${fmtUsd(live.equity_usd)}</span><span class="muted small">equity ahora</span>` +
    deltaHtml +
    `<span class="muted small">cash ${fmtUsd(live.cash_usd)}</span>`;
  tbody.innerHTML = "";
  for (const p of live.positions || []) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${p.symbol}</td><td>${p.qty}</td><td>${fmtUsd(p.price)}</td>` +
                   `<td>${fmtUsd(p.value_usd)}</td><td>${fmtPct(p.weight)}</td>`;
    tbody.appendChild(tr);
  }
  if (!(live.positions || []).length) {
    tbody.innerHTML = "<tr><td colspan='5' class='muted'>Sin tenencias.</td></tr>";
  }
  renderLiveChart(officialSeries, live);
  note.textContent = `${live.note} · consultado ${live.as_of}`;
}

async function main() {
  const snap = await loadSnapshot();
  const series = snap && snap.equity ? snap.equity.series || [] : [];
  const refreshBtn = document.getElementById("live-refresh");
  if (refreshBtn) {
    // Guard anti-caché-mixto: si el HTML viejo no trae el card, la página
    // oficial sigue renderizando (bug visto 2026-07-04).
    refreshBtn.addEventListener("click", () => renderLive(series));
    renderLive(series);
  }
  if (!snap) return;
  document.getElementById("generated").textContent = "snapshot: " + (snap.generated_at || "");

  const shap = snap.shap || { symbols: {} };
  renderPortfolio(snap.portfolio);
  renderEquity(snap.equity);
  renderSignals(snap.signals);
  renderDebate(snap.debate);
  renderCost(snap.cost);
  renderPositions(snap.positions);

  if (!shap.available) {
    document.getElementById("shap-card").classList.add("warn");
    document.getElementById("prediction").innerHTML =
      "<span class='muted'>SHAP no disponible: " + (shap.reason || "sin modelo") + "</span>";
    return;
  }

  const symbols = renderSymbolSelect(shap);
  const sel = document.getElementById("symbol-select");
  const draw = () => {
    const entry = shap.symbols[sel.value];
    if (!entry) return;
    renderPrediction(entry);
    renderWaterfall(entry);
    renderFeatures(entry);
  };
  sel.addEventListener("change", draw);
  if (symbols.length) { sel.value = symbols[0]; draw(); }
}

main();
