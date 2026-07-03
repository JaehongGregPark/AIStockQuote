const state = {
  markets: [],
  selectedMarket: null,
  quotesByMarket: {},
  chart: null,
};

const els = {
  tabs: document.getElementById("market-tabs"),
  desc: document.getElementById("market-desc"),
  content: document.getElementById("content"),
  modalBackdrop: document.getElementById("modal-backdrop"),
  modalBody: document.getElementById("modal-body"),
  closeModal: document.getElementById("close-modal"),
};

els.closeModal.addEventListener("click", closeModal);
els.modalBackdrop.addEventListener("click", (e) => {
  if (e.target === els.modalBackdrop) closeModal();
});

init();

async function init() {
  const res = await fetch("/api/markets");
  state.markets = await res.json();
  renderTabs();
  selectMarket(state.markets[0].id);
}

function renderTabs() {
  els.tabs.innerHTML = "";
  state.markets.forEach((market) => {
    const btn = document.createElement("button");
    btn.className = "tab" + (market.id === state.selectedMarket ? " active" : "");
    btn.textContent = market.title;
    btn.addEventListener("click", () => selectMarket(market.id));
    els.tabs.appendChild(btn);
  });
}

async function selectMarket(marketId) {
  state.selectedMarket = marketId;
  renderTabs();
  const market = state.markets.find((m) => m.id === marketId);
  els.desc.textContent = market ? market.description : "";
  els.content.innerHTML = '<div class="loading">불러오는 중…</div>';

  try {
    const res = await fetch(`/api/markets/${marketId}/quotes`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.quotesByMarket[marketId] = data;
    renderQuoteList(data);
  } catch (err) {
    renderError(err.message, () => selectMarket(marketId));
  }
}

function renderError(message, onRetry) {
  els.content.innerHTML = "";
  const status = document.createElement("div");
  status.className = "status";
  status.textContent = message || "시세를 불러오지 못했습니다.";
  const retry = document.createElement("button");
  retry.className = "retry";
  retry.textContent = "다시 시도";
  retry.addEventListener("click", onRetry);
  els.content.appendChild(status);
  els.content.appendChild(retry);
}

function renderQuoteList(data) {
  els.content.innerHTML = "";

  if (data.failed_symbols && data.failed_symbols.length > 0) {
    const note = document.createElement("div");
    note.className = "failed-note";
    note.textContent = `일부 종목을 불러오지 못했습니다: ${data.failed_symbols.join(", ")}`;
    els.content.appendChild(note);
  }

  const list = document.createElement("div");
  list.id = "quote-list";

  data.quotes.forEach((quote) => {
    list.appendChild(renderQuoteItem(quote));
  });

  els.content.appendChild(list);
}

function renderQuoteItem(quote) {
  const item = document.createElement("div");
  item.className = "quote-item";
  item.addEventListener("click", () => openDetail(quote.symbol));

  const isUp = (quote.change_amount ?? 0) >= 0;
  const pct = quote.change_percent != null ? `${quote.change_percent.toFixed(2)}%` : "-";

  item.innerHTML = `
    <div class="row">
      <div>
        <div class="name">${quote.short_name || quote.symbol}</div>
        <div class="symbol">${quote.symbol}</div>
      </div>
      <div class="price">${formatNumber(quote.price, quote.currency)}</div>
    </div>
    <div class="meta">
      <span>${quote.exchange_name || "-"}</span>
      <span class="change ${isUp ? "up" : "down"}">${isUp ? "+" : ""}${pct}</span>
    </div>
  `;
  return item;
}

async function openDetail(symbol) {
  els.modalBackdrop.classList.remove("hidden");
  els.modalBody.innerHTML = '<div class="loading">불러오는 중…</div>';

  try {
    const res = await fetch(`/api/quotes/${encodeURIComponent(symbol)}?market=${state.selectedMarket}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const quote = await res.json();
    renderDetail(quote);
  } catch (err) {
    els.modalBody.innerHTML = `<div class="status">${err.message}</div>`;
  }
}

function closeModal() {
  els.modalBackdrop.classList.add("hidden");
  if (state.chart) {
    state.chart.destroy();
    state.chart = null;
  }
}

function renderDetail(quote) {
  const isUp = (quote.change_amount ?? 0) >= 0;
  const pct = quote.change_percent != null ? `${quote.change_percent.toFixed(2)}%` : "-";
  const changeText = quote.change_amount != null ? formatNumber(quote.change_amount, quote.currency) : "-";

  els.modalBody.innerHTML = `
    <div class="detail-card">
      <div class="symbol">${quote.symbol}</div>
      <div class="name">${quote.short_name || quote.symbol}</div>
      <div class="detail-price">${formatNumber(quote.price, quote.currency)}</div>
      <div class="change ${isUp ? "up" : "down"}">${isUp ? "+" : ""}${changeText} (${pct})</div>
    </div>
    <div class="chart-card">
      <h3>1M Price Chart</h3>
      <canvas id="price-chart"></canvas>
    </div>
    <div class="info-grid">
      ${infoCell("Exchange", quote.exchange_name || "-")}
      ${infoCell("Currency", quote.currency || "-")}
      ${infoCell("Open", quote.open_price != null ? formatNumber(quote.open_price, quote.currency) : "-")}
      ${infoCell("High", quote.day_high != null ? formatNumber(quote.day_high, quote.currency) : "-")}
      ${infoCell("Low", quote.day_low != null ? formatNumber(quote.day_low, quote.currency) : "-")}
      ${infoCell("Updated", quote.market_time ? formatDateTime(quote.market_time) : "-")}
    </div>
    <div class="ai-card" id="ai-card">
      <h3>AI 분석</h3>
      <button class="ai-btn" id="ai-btn">AI 해설 보기</button>
      <div id="ai-output"></div>
    </div>
  `;

  renderChart(quote.chart_points);

  document.getElementById("ai-btn").addEventListener("click", () => loadAiAnalysis(quote.symbol));
}

function infoCell(label, value) {
  return `<div class="info-cell"><div class="label">${label}</div><div class="value">${value}</div></div>`;
}

function renderChart(points) {
  const ctx = document.getElementById("price-chart");
  if (!ctx) return;

  if (state.chart) {
    state.chart.destroy();
    state.chart = null;
  }

  if (!points || points.length < 2) {
    ctx.replaceWith(document.createTextNode("차트 데이터가 없습니다."));
    return;
  }

  state.chart = new Chart(ctx, {
    type: "line",
    data: {
      labels: points.map((p) => new Date(p.timestamp * 1000).toLocaleDateString()),
      datasets: [
        {
          data: points.map((p) => p.close),
          borderColor: "#2563eb",
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.2,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { display: false },
        y: { display: true },
      },
    },
  });
}

async function loadAiAnalysis(symbol) {
  const btn = document.getElementById("ai-btn");
  const output = document.getElementById("ai-output");
  btn.disabled = true;
  output.innerHTML = '<div class="loading">AI가 분석 중…</div>';

  try {
    const res = await fetch(`/api/quotes/${encodeURIComponent(symbol)}/analysis?market=${state.selectedMarket}`);
    const data = await res.json();
    if (!data.available) {
      output.innerHTML = '<div class="ai-disabled">AI 분석 기능이 비활성화되어 있습니다 (ANTHROPIC_API_KEY 미설정).</div>';
    } else {
      output.innerHTML = `<div class="ai-text">${data.analysis || "분석 결과가 없습니다."}</div>`;
    }
  } catch (err) {
    output.innerHTML = `<div class="status">AI 분석을 불러오지 못했습니다.</div>`;
  } finally {
    btn.disabled = false;
  }
}

function formatNumber(value, currency) {
  const formatted = Number(value).toLocaleString("en-US", {
    minimumFractionDigits: value < 10 ? 2 : 0,
    maximumFractionDigits: 2,
  });
  return currency ? `${formatted} ${currency}` : formatted;
}

function formatDateTime(epochSeconds) {
  const date = new Date(epochSeconds * 1000);
  return date.toLocaleString("ko-KR");
}
