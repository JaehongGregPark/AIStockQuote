const SETTINGS_TAB_ID = "__settings__";

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

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value ?? "";
  return div.innerHTML;
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

  const settingsBtn = document.createElement("button");
  settingsBtn.className = "tab" + (state.selectedMarket === SETTINGS_TAB_ID ? " active" : "");
  settingsBtn.textContent = "설정";
  settingsBtn.addEventListener("click", () => selectMarket(SETTINGS_TAB_ID));
  els.tabs.appendChild(settingsBtn);
}

async function selectMarket(marketId) {
  state.selectedMarket = marketId;
  renderTabs();

  if (marketId === SETTINGS_TAB_ID) {
    els.desc.textContent = "AI 분석에 사용할 LLM 제공자의 API 키·모델을 설정합니다.";
    renderSettingsTab();
    return;
  }

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

function renderSettingsTab() {
  els.content.innerHTML = `
    <div class="settings-section">
      <h2>AI 제공자 API 키 / 모델</h2>
      <p class="settings-hint">각 제공자의 API 키와 모델을 입력한 뒤 "테스트"를 누르면 실제로
        호출해 상태를 확인하고, 입력한 값을 .env 파일에도 저장합니다.</p>
      <div class="settings-provider-grid" id="settings-provider-list">
        <div class="loading">확인 중…</div>
      </div>
    </div>
    <div class="settings-section">
      <h2>사용할 AI 제공자</h2>
      <p class="settings-hint">아래에서 3개 제공자 중 하나를 선택하고 저장하면, 이후 AI 분석은
        그 제공자(API 키·모델)로 수행됩니다. "자동"을 선택하면 anthropic → openai → gemini
        순서로 설정된 첫 번째 키를 사용합니다.</p>
      <div class="active-provider-form">
        <select id="active-provider-select">
          <option value="">자동 (anthropic → openai → gemini 우선순위)</option>
          <option value="anthropic">anthropic</option>
          <option value="openai">openai</option>
          <option value="gemini">gemini</option>
        </select>
        <button type="button" id="active-provider-save-btn">저장</button>
        <div class="api-key-save-status" id="active-provider-status"></div>
      </div>
    </div>
  `;

  document
    .getElementById("active-provider-save-btn")
    .addEventListener("click", saveActiveProvider);

  loadApiKeyStatus();
}

async function loadApiKeyStatus() {
  const listEl = document.getElementById("settings-provider-list");
  if (!listEl) return; // user navigated away from the settings tab
  listEl.innerHTML = '<div class="loading">확인 중…</div>';

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 20000);

  try {
    const res = await fetch("/api/ai/status", { signal: controller.signal });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderApiKeyStatus(data.providers || []);

    const select = document.getElementById("active-provider-select");
    if (select) {
      select.value = data.ai_provider_override || "";
    }
  } catch (err) {
    const message =
      err.name === "AbortError"
        ? "응답이 너무 오래 걸려 확인을 중단했습니다. 서버 로그를 확인해주세요."
        : "API 키 상태를 확인하지 못했습니다.";
    const listEl2 = document.getElementById("settings-provider-list");
    if (listEl2) listEl2.innerHTML = `<div class="api-key-error">${message}</div>`;
  } finally {
    clearTimeout(timeoutId);
  }
}

function renderApiKeyStatus(providers) {
  const listEl = document.getElementById("settings-provider-list");
  if (!listEl) return;
  listEl.innerHTML = "";
  providers.forEach((p) => {
    listEl.appendChild(renderApiKeyItem(p));
  });
}

function renderApiKeyItem(p) {
  const item = document.createElement("div");
  item.className = "api-key-item" + (p.is_active ? " active" : "");

  const badgeClass = p.usable ? "badge-ok" : "badge-fail";
  const badgeText = p.configured ? (p.usable ? "사용 가능" : "사용 불가") : "미설정";

  let extra = "";
  if (p.configured && !p.usable) {
    extra += `<div class="api-key-error">${escapeHtml(p.error) || "알 수 없는 오류"}</div>`;
    if (p.available_models && p.available_models.length > 0) {
      extra += `
        <div class="api-key-models-label">현재 키로 사용 가능한 모델:</div>
        <ul class="api-key-models-list">${p.available_models.map((m) => `<li>${escapeHtml(m)}</li>`).join("")}</ul>
      `;
    }
  }

  item.innerHTML = `
    <div class="api-key-row">
      <span class="api-key-provider">${escapeHtml(p.provider)}</span>
      <span class="api-key-badges">
        ${p.is_active ? '<span class="badge badge-active">사용 중</span>' : ""}
        <span class="badge ${badgeClass}">${badgeText}</span>
      </span>
    </div>
    <div class="api-key-model">모델: ${escapeHtml(p.model) || "-"}</div>
    ${extra}
    <div class="api-key-form">
      <input
        type="password"
        class="api-key-input"
        placeholder="${p.configured ? "API 키 변경" : "API 키 입력"}"
        autocomplete="off"
      />
      <input
        type="text"
        class="api-key-model-input"
        placeholder="모델명"
        value="${escapeHtml(p.model)}"
      />
      <button type="button" class="api-key-save-btn">테스트</button>
      <div class="api-key-save-status"></div>
    </div>
  `;

  const apiKeyInput = item.querySelector(".api-key-input");
  const modelInput = item.querySelector(".api-key-model-input");
  const saveBtn = item.querySelector(".api-key-save-btn");
  const saveStatus = item.querySelector(".api-key-save-status");

  saveBtn.addEventListener("click", () => saveProviderConfig(p.provider, apiKeyInput, modelInput, saveBtn, saveStatus));

  return item;
}

async function saveProviderConfig(provider, apiKeyInput, modelInput, saveBtn, saveStatus) {
  saveBtn.disabled = true;
  saveStatus.textContent = "테스트 중…";

  try {
    const res = await fetch(`/api/ai/config/${encodeURIComponent(provider)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        api_key: apiKeyInput.value.trim() || null,
        model: modelInput.value.trim() || null,
      }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    apiKeyInput.value = "";
    const statusText = data.usable ? "사용 가능" : `사용 불가 (${data.error || "알 수 없는 오류"})`;
    saveStatus.textContent = data.persisted_to_env
      ? `${statusText} — 저장됨 (.env에 기록됨)`
      : statusText;
    // brief pause so the confirmation is visible before the panel re-renders
    await new Promise((resolve) => setTimeout(resolve, 900));
    await loadApiKeyStatus();
  } catch (err) {
    saveStatus.textContent = "테스트하지 못했습니다.";
    saveBtn.disabled = false;
  }
}

async function saveActiveProvider() {
  const select = document.getElementById("active-provider-select");
  const statusEl = document.getElementById("active-provider-status");
  const btn = document.getElementById("active-provider-save-btn");
  if (!select || !statusEl || !btn) return;

  btn.disabled = true;
  statusEl.textContent = "저장 중…";

  try {
    const res = await fetch("/api/ai/active-provider", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider: select.value || null }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    statusEl.textContent = `저장됨 (.env에 기록됨) — 현재 사용 중: ${data.active_provider || "-"}`;
    await new Promise((resolve) => setTimeout(resolve, 700));
    await loadApiKeyStatus();
  } catch (err) {
    statusEl.textContent = "저장하지 못했습니다.";
  } finally {
    btn.disabled = false;
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
      output.innerHTML = '<div class="ai-disabled">AI 분석 기능이 비활성화되어 있습니다 (API 키 미설정).</div>';
    } else if (data.error) {
      const modelsList =
        data.available_models && data.available_models.length > 0
          ? `<div class="ai-models-label">현재 키(${data.provider || "-"})로 사용 가능한 모델:</div>
             <ul class="ai-models-list">${data.available_models.map((m) => `<li>${m}</li>`).join("")}</ul>`
          : `<div class="ai-models-label">현재 키로 사용 가능한 모델 목록을 가져오지 못했습니다.</div>`;
      output.innerHTML = `
        <div class="status">AI 분석 실패 (${data.provider || "-"}): ${data.error}</div>
        ${modelsList}
      `;
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
