"use strict";

let waterfallChart = null;

async function loadSnapshot() {
  const res = await fetch("/api/snapshot");
  if (!res.ok) return null;
  return res.json();
}

function fmtUsd(x) { return "$" + Number(x).toFixed(4); }

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

async function main() {
  const snap = await loadSnapshot();
  if (!snap) return;
  document.getElementById("generated").textContent = "snapshot: " + (snap.generated_at || "");

  const shap = snap.shap || { symbols: {} };
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
