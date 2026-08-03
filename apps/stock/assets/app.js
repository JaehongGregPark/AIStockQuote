const SETTINGS_TAB_ID = "__settings__";
const NEWS_TAB_ID = "__news__";
const isStockAdmin = document.body.dataset.stockAdmin === "true";

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
els.modalBackdrop.addEventListener("click", (event) => {
  if (event.target === els.modalBackdrop) closeModal();
});

init();
document.getElementById("stock-search-btn")?.addEventListener("click", searchStocks);

async function searchStocks() {
  const query = document.getElementById("stock-search-input").value.trim();
  const target = document.getElementById("stock-search-results");
  const res = await fetch(`/stock/api/stocks/search?q=${encodeURIComponent(query)}`);
  const data = await res.json();
  target.innerHTML = (data.results || []).map(item => `<button class="secondary-action" data-search-symbol="${escapeHtml(item.symbol)}">${escapeHtml(item.name)} · ${escapeHtml(item.symbol)} · ${escapeHtml(item.market)}</button>`).join(" ") || "검색 결과가 없습니다.";
  target.querySelectorAll("[data-search-symbol]").forEach(button => button.addEventListener("click", () => openDetail(button.dataset.searchSymbol)));
}

async function init() {
  const res = await fetch("/stock/api/markets");
  state.markets = await res.json();
  renderTabs();
  selectMarket(isStockAdmin ? SETTINGS_TAB_ID : state.markets[0].id);
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value ?? "";
  return div.innerHTML;
}

function getCookie(name) {
  const cookies = document.cookie ? document.cookie.split(";") : [];
  for (const cookie of cookies) {
    const [rawKey, ...rawValue] = cookie.trim().split("=");
    if (rawKey === name) return decodeURIComponent(rawValue.join("="));
  }
  return "";
}

function csrfHeaders() {
  const token = getCookie("csrftoken");
  return token ? { "X-CSRFToken": token } : {};
}

function renderTabs() {
  els.tabs.innerHTML = "";

  if (isStockAdmin) {
    const settingsBtn = document.createElement("button");
    settingsBtn.className = "tab active";
    settingsBtn.textContent = "API key management";
    settingsBtn.addEventListener("click", () => selectMarket(SETTINGS_TAB_ID));
    els.tabs.appendChild(settingsBtn);
    return;
  }

  state.markets.forEach((market) => {
    const btn = document.createElement("button");
    btn.className = "tab" + (market.id === state.selectedMarket ? " active" : "");
    btn.textContent = market.title;
    btn.addEventListener("click", () => selectMarket(market.id));
    els.tabs.appendChild(btn);
  });

  const newsBtn = document.createElement("button");
  newsBtn.className = "tab" + (state.selectedMarket === NEWS_TAB_ID ? " active" : "");
  newsBtn.textContent = "주식뉴스";
  newsBtn.addEventListener("click", () => selectMarket(NEWS_TAB_ID));
  els.tabs.appendChild(newsBtn);
}

async function selectMarket(marketId) {
  if (marketId === SETTINGS_TAB_ID && !isStockAdmin) {
    selectMarket(state.markets[0].id);
    return;
  }

  state.selectedMarket = marketId;
  renderTabs();
  stopSpeech(); // 뉴스 탭을 떠나거나 새 목록을 불러올 때는 재생 중인 TTS를 멈춘다.

  if (marketId === SETTINGS_TAB_ID) {
    renderSettingsTab();
    return;
  }

  if (marketId === NEWS_TAB_ID) {
    renderNewsTab();
    return;
  }

  const market = state.markets.find((item) => item.id === marketId);
  els.desc.textContent = market ? market.description : "";
  els.content.innerHTML = '<div class="loading">Loading quotes...</div>';

  try {
    const res = await fetch(`/stock/api/markets/${marketId}/quotes`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.quotesByMarket[marketId] = data;
    renderQuoteList(data);
  } catch (err) {
    renderError(err.message, () => selectMarket(marketId));
  }
}

function renderSettingsTab() {
  els.desc.textContent = "Stock admin";
  els.content.innerHTML = `
    <div class="settings-section stock-admin-panel">
      <div class="stock-admin-panel-head">
        <div>
          <h2>AI provider API key management</h2>
          <p class="settings-hint">Manage each provider in the same row-based style used by the AURA admin screen.</p>
        </div>
        <button type="button" class="secondary-action" id="reload-provider-status">Refresh status</button>
      </div>
      <div class="settings-provider-grid" id="settings-provider-list">
        <div class="loading">Checking providers...</div>
      </div>
    </div>
    <div class="settings-section">
      <h2>Active AI provider</h2>
      <p class="settings-hint">Auto uses the first configured provider in this order: anthropic, openai, gemini.</p>
      <div class="active-provider-form">
        <select id="active-provider-select">
          <option value="">Auto</option>
          <option value="anthropic">anthropic</option>
          <option value="openai">openai</option>
          <option value="gemini">gemini</option>
        </select>
        <button type="button" id="active-provider-save-btn">Save</button>
        <div class="api-key-save-status" id="active-provider-status"></div>
      </div>
    </div>
    <div class="settings-section stock-admin-panel">
      <div class="stock-admin-panel-head">
        <div>
          <h2>뉴스 API 키 관리 (GNews · 주식뉴스 탭)</h2>
          <p class="settings-hint">"주식뉴스" 메뉴가 사용하는 키입니다. AeroGo(바둑뉴스)와 허브 전체가 이 key 하나를 공유합니다 -- 저장하면 재시작 없이 즉시 반영되고 .env에도 기록됩니다.</p>
        </div>
      </div>
      <div class="settings-provider-grid" id="news-key-panel">
        <div class="loading">불러오는 중...</div>
      </div>
    </div>
    <div class="settings-section stock-admin-panel">
      <div class="stock-admin-panel-head">
        <div>
          <h2>소셜 로그인 관리 (카카오 · 네이버 · 구글 · 애플)</h2>
          <p class="settings-hint">허브 전체 5개 서브앱(aura/stock/aerogo/origin)이 공유하는 설정입니다. 저장하면 재시작 없이 즉시 반영되고 .env에도 기록됩니다.</p>
        </div>
        <button type="button" class="secondary-action" id="reload-social-status">Refresh status</button>
      </div>
      <div class="settings-provider-grid" id="settings-social-list">
        <div class="loading">불러오는 중...</div>
      </div>
    </div>
  `;

  document.getElementById("reload-provider-status").addEventListener("click", loadApiKeyStatus);
  document.getElementById("active-provider-save-btn").addEventListener("click", saveActiveProvider);
  document.getElementById("reload-social-status").addEventListener("click", loadSocialLoginStatus);
  loadApiKeyStatus();
  loadSocialLoginStatus();
  loadNewsKeyStatus();
}

async function loadNewsKeyStatus() {
  const panel = document.getElementById("news-key-panel");
  if (!panel) return;
  panel.innerHTML = '<div class="loading">불러오는 중...</div>';

  try {
    const res = await fetch("/stock/api/news/validate", { method: "POST", headers: csrfHeaders() });
    // validate 호출은 상태를 새로 확인하는 김에 provider 정보도 함께 받아온다.
    // 저장된 key가 없을 때는 검증 자체가 무의미하므로 조용히 무시하고 상태만 그린다.
    const data = res.ok ? await res.json() : null;
    renderNewsKeyPanel(data && data.provider ? data.provider : { hasKey: false, maskedKey: "" }, data);
  } catch (err) {
    renderNewsKeyPanel({ hasKey: false, maskedKey: "" }, null);
  }
}

function renderNewsKeyPanel(provider, validation) {
  const panel = document.getElementById("news-key-panel");
  if (!panel) return;

  const validationText = validation
    ? `${validation.valid ? "검증 성공" : "검증 실패"}: ${escapeHtml(validation.message || "")}`
    : "아직 검증하지 않았습니다.";
  const validationClass = validation ? (validation.valid ? "is-ok" : "is-error") : "";

  panel.innerHTML = `
    <div class="api-key-item provider-row">
      <div class="provider-name-cell">
        <div class="api-key-provider">GNews</div>
        <div class="api-key-badges"><span class="badge ${provider.hasKey ? "badge-ok" : "badge-fail"}">${provider.hasKey ? "설정됨" : "미설정"}</span></div>
      </div>
      <label>API key
        <input type="password" id="news-key-input" placeholder="${provider.hasKey ? "새 API key 입력" : "GNews API key 입력"}" autocomplete="off" />
        <span class="provider-key-hint">${provider.hasKey ? `저장됨: ${escapeHtml(provider.maskedKey || "")}` : "저장된 key 없음"}</span>
      </label>
      <button type="button" class="api-key-save-btn" id="news-key-save-btn">저장</button>
      <button type="button" class="api-key-save-btn" id="news-key-validate-btn">키 검증</button>
      <div class="api-key-save-status" id="news-key-save-status"></div>
      <div class="provider-validation ${validationClass}">${validationText}</div>
    </div>
  `;

  document.getElementById("news-key-save-btn").addEventListener("click", saveNewsApiKey);
  document.getElementById("news-key-validate-btn").addEventListener("click", loadNewsKeyStatus);
}

async function saveNewsApiKey() {
  const input = document.getElementById("news-key-input");
  const statusEl = document.getElementById("news-key-save-status");
  const value = input.value.trim();
  if (!value) {
    statusEl.textContent = "저장할 key를 입력해 주세요.";
    return;
  }

  statusEl.textContent = "저장 중...";
  try {
    const res = await fetch("/stock/api/news/config", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...csrfHeaders() },
      body: JSON.stringify({ api_key: value }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.detail || "저장 실패");
    input.value = "";
    statusEl.textContent = "저장되었습니다. 검증 중...";
    await loadNewsKeyStatus();
  } catch (err) {
    statusEl.textContent = `저장 실패: ${err.message}`;
  }
}

async function loadSocialLoginStatus() {
  const listEl = document.getElementById("settings-social-list");
  if (!listEl) return;
  listEl.innerHTML = '<div class="loading">불러오는 중...</div>';

  try {
    const res = await fetch("/stock/api/social-login/status");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    listEl.innerHTML = "";
    (data.providers || []).forEach((provider) => listEl.appendChild(renderSocialLoginItem(provider)));
  } catch (err) {
    listEl.innerHTML = '<div class="api-key-error">소셜 로그인 설정을 불러오지 못했습니다.</div>';
  }
}

function renderSocialLoginItem(provider) {
  const item = document.createElement("div");
  item.className = "api-key-item provider-row";

  const badgeClass = provider.configured ? "badge-ok" : "badge-fail";
  const badgeText = provider.configured ? "설정됨" : "미설정";
  const testLink = provider.configured
    ? `<a class="provider-model" href="/stock/api/auth/social/${provider.provider}/start/?privacyConsentAccepted=1" target="_blank">실제 로그인 화면 테스트 →</a>`
    : '<span class="provider-model">Client ID를 저장하면 테스트 링크가 나타납니다</span>';

  item.innerHTML = `
    <div class="provider-name-cell">
      <div class="api-key-provider">${escapeHtml(provider.label)}</div>
      <div class="api-key-badges"><span class="badge ${badgeClass}">${badgeText}</span></div>
    </div>
    <label>Client ID
      <input type="text" class="social-client-id-input" placeholder="${provider.has_client_id ? "새 Client ID 입력" : "Client ID 입력"}" autocomplete="off" />
      <span class="provider-key-hint">${provider.has_client_id ? `저장됨: ${escapeHtml(provider.client_id_masked || "")}` : "저장된 값 없음"}</span>
    </label>
    <label>Client Secret ${provider.requires_secret ? "(필수)" : "(선택)"}
      <input type="text" class="social-client-secret-input" placeholder="${provider.has_client_secret ? "새 Client Secret 입력" : "Client Secret 입력"}" autocomplete="off" />
      <span class="provider-key-hint">${provider.has_client_secret ? `저장됨: ${escapeHtml(provider.client_secret_masked || "")}` : "저장된 값 없음"}</span>
    </label>
    <button type="button" class="api-key-save-btn">저장</button>
    <div class="api-key-save-status"></div>
    <div class="provider-models">${testLink}</div>
  `;

  const clientIdInput = item.querySelector(".social-client-id-input");
  const clientSecretInput = item.querySelector(".social-client-secret-input");
  const saveBtn = item.querySelector(".api-key-save-btn");
  const saveStatus = item.querySelector(".api-key-save-status");

  saveBtn.addEventListener("click", () =>
    saveSocialProviderConfig(provider.provider, clientIdInput, clientSecretInput, saveBtn, saveStatus)
  );
  return item;
}

async function saveSocialProviderConfig(provider, clientIdInput, clientSecretInput, saveBtn, saveStatus) {
  saveBtn.disabled = true;
  saveStatus.textContent = "저장 중...";

  try {
    const res = await fetch(`/stock/api/social-login/config/${encodeURIComponent(provider)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...csrfHeaders() },
      body: JSON.stringify({
        client_id: clientIdInput.value.trim() || null,
        client_secret: clientSecretInput.value.trim() || null,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);

    clientIdInput.value = "";
    clientSecretInput.value = "";
    saveStatus.textContent = "저장되었습니다.";
    await new Promise((resolve) => setTimeout(resolve, 700));
    await loadSocialLoginStatus();
  } catch (err) {
    saveStatus.textContent = `저장 실패: ${err.message}`;
    saveBtn.disabled = false;
  }
}

async function loadApiKeyStatus() {
  const listEl = document.getElementById("settings-provider-list");
  if (!listEl) return;
  listEl.innerHTML = '<div class="loading">Checking providers...</div>';

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 25000);

  try {
    const res = await fetch("/stock/api/ai/status", { signal: controller.signal });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderApiKeyStatus(data.providers || []);

    const select = document.getElementById("active-provider-select");
    if (select) select.value = data.ai_provider_override || "";
  } catch (err) {
    const message =
      err.name === "AbortError"
        ? "Provider validation timed out. Check the server log and try again."
        : "Could not load API key status.";
    const target = document.getElementById("settings-provider-list");
    if (target) target.innerHTML = `<div class="api-key-error">${message}</div>`;
  } finally {
    clearTimeout(timeoutId);
  }
}

function renderApiKeyStatus(providers) {
  const listEl = document.getElementById("settings-provider-list");
  if (!listEl) return;
  listEl.innerHTML = "";
  providers.forEach((provider) => {
    listEl.appendChild(renderApiKeyItem(provider));
  });
}

function renderApiKeyItem(provider) {
  const item = document.createElement("div");
  item.className = "api-key-item provider-row" + (provider.is_active ? " active" : "");

  const badgeClass = provider.usable ? "badge-ok" : "badge-fail";
  const badgeText = provider.configured ? (provider.usable ? "Valid" : "Invalid") : "Not set";
  const validationClass = provider.usable ? "is-ok" : provider.configured ? "is-error" : "";
  const validationText = provider.configured
    ? provider.usable
      ? "Validation succeeded"
      : `Validation failed: ${provider.error || "Unknown error"}`
    : "No saved API key.";
  const models = Array.isArray(provider.available_models) ? provider.available_models : [];
  const modelsHtml = models.length
    ? models.map((model) => `<span class="provider-model" title="${escapeHtml(model)}">${escapeHtml(model)}</span>`).join("")
    : '<span class="provider-model">Models appear after validation</span>';

  item.innerHTML = `
    <div class="provider-name-cell">
      <div class="api-key-provider">${escapeHtml(provider.provider)}</div>
      <div class="api-key-badges">
        ${provider.is_active ? '<span class="badge badge-active">Active</span>' : ""}
        <span class="badge ${badgeClass}">${badgeText}</span>
      </div>
    </div>
    <label>LLM version
      <input type="text" class="api-key-model-input" value="${escapeHtml(provider.model || "")}" placeholder="ex: gpt-4.1-mini" />
    </label>
    <label>New API key
      <input type="password" class="api-key-input" placeholder="${provider.has_key ? "Enter new key" : "Enter API key"}" autocomplete="off" />
      <span class="provider-key-hint">${provider.has_key ? `Saved: ${escapeHtml(provider.masked_key || "")}` : "No saved key"}</span>
    </label>
    <button type="button" class="api-key-save-btn">Validate key</button>
    <div class="api-key-save-status"></div>
    <div class="provider-validation ${validationClass}">${escapeHtml(validationText)}</div>
    <div class="provider-models">${modelsHtml}</div>
  `;

  const apiKeyInput = item.querySelector(".api-key-input");
  const modelInput = item.querySelector(".api-key-model-input");
  const saveBtn = item.querySelector(".api-key-save-btn");
  const saveStatus = item.querySelector(".api-key-save-status");

  saveBtn.addEventListener("click", () => saveProviderConfig(provider.provider, apiKeyInput, modelInput, saveBtn, saveStatus));
  return item;
}

async function saveProviderConfig(provider, apiKeyInput, modelInput, saveBtn, saveStatus) {
  saveBtn.disabled = true;
  saveStatus.textContent = "Validating...";

  try {
    const res = await fetch(`/stock/api/ai/config/${encodeURIComponent(provider)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...csrfHeaders() },
      body: JSON.stringify({
        api_key: apiKeyInput.value.trim() || null,
        model: modelInput.value.trim() || null,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);

    apiKeyInput.value = "";
    saveStatus.textContent = data.usable ? "Valid and saved" : `Invalid: ${data.error || "Unknown error"}`;
    await new Promise((resolve) => setTimeout(resolve, 700));
    await loadApiKeyStatus();
  } catch (err) {
    saveStatus.textContent = `Validation failed: ${err.message}`;
    saveBtn.disabled = false;
  }
}

async function saveActiveProvider() {
  const select = document.getElementById("active-provider-select");
  const statusEl = document.getElementById("active-provider-status");
  const btn = document.getElementById("active-provider-save-btn");
  if (!select || !statusEl || !btn) return;

  btn.disabled = true;
  statusEl.textContent = "Saving...";

  try {
    const res = await fetch("/stock/api/ai/active-provider", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...csrfHeaders() },
      body: JSON.stringify({ provider: select.value || null }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);

    statusEl.textContent = `Saved. Active provider: ${data.active_provider || "-"}`;
    await new Promise((resolve) => setTimeout(resolve, 700));
    await loadApiKeyStatus();
  } catch (err) {
    statusEl.textContent = `Save failed: ${err.message}`;
  } finally {
    btn.disabled = false;
  }
}

function renderError(message, onRetry) {
  els.content.innerHTML = "";
  const status = document.createElement("div");
  status.className = "status";
  status.textContent = message || "Could not load data.";
  const retry = document.createElement("button");
  retry.className = "retry";
  retry.textContent = "Retry";
  retry.addEventListener("click", onRetry);
  els.content.appendChild(status);
  els.content.appendChild(retry);
}

// --- 주식뉴스 탭 (2026-07-22 신설, GNews API + 브라우저 TTS) -------------------

async function renderNewsTab() {
  els.desc.textContent = "국내외 주식·증시 관련 최신 뉴스입니다 (제공: GNews).";
  els.content.innerHTML = '<div class="loading">뉴스를 불러오는 중...</div>';

  try {
    const res = await fetch("/stock/api/news");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderNewsCards(data);
  } catch (err) {
    renderError("뉴스를 불러오지 못했습니다.", renderNewsTab);
  }
}

function renderNewsCards(data) {
  els.content.innerHTML = "";

  if (!data.available) {
    const notice = document.createElement("div");
    notice.className = "status";
    notice.textContent =
      data.reason === "no_key"
        ? "뉴스 API key가 아직 설정되어 있지 않습니다. 관리자 설정에서 GNews API key를 등록해 주세요."
        : `뉴스를 불러오지 못했습니다: ${data.error || "알 수 없는 오류"}`;
    els.content.appendChild(notice);
    return;
  }

  if (data.stale && data.warning) {
    const warn = document.createElement("div");
    warn.className = "failed-note";
    warn.textContent = `최신 뉴스를 불러오지 못해 이전 결과를 보여줍니다: ${data.warning}`;
    els.content.appendChild(warn);
  }

  const articles = data.articles || [];
  const grid = document.createElement("div");
  grid.className = "news-grid";

  if (articles.length === 0) {
    grid.innerHTML = '<div class="status">표시할 뉴스가 없습니다.</div>';
  } else {
    articles.forEach((article) => grid.appendChild(renderNewsCard(article)));
  }
  els.content.appendChild(grid);
}

function renderNewsCard(article) {
  const card = document.createElement("div");
  card.className = "news-card";

  const speakText = [article.title, article.description].filter(Boolean).join(". ");
  const published = article.publishedAt ? new Date(article.publishedAt).toLocaleString("ko-KR") : "";

  card.innerHTML = `
    ${article.image ? `<img class="news-card-image" src="${escapeHtml(article.image)}" alt="" loading="lazy">` : ""}
    <div class="news-card-body">
      <div class="news-card-head">
        <h3 class="news-card-title">${escapeHtml(article.title)}</h3>
        <button type="button" class="news-tts-button" aria-label="뉴스 듣기" title="듣기">🔊</button>
      </div>
      <p class="news-card-desc">${escapeHtml(article.description || "")}</p>
      <div class="news-card-meta">
        <span>${escapeHtml(article.sourceName || "출처 미상")}</span>
        <span>${escapeHtml(published)}</span>
      </div>
      ${article.url ? `<a class="news-card-link" href="${escapeHtml(article.url)}" target="_blank" rel="noreferrer">원문 보기 →</a>` : ""}
    </div>
  `;

  const image = card.querySelector(".news-card-image");
  if (image) image.addEventListener("error", () => image.remove());

  const ttsButton = card.querySelector(".news-tts-button");
  ttsButton.addEventListener("click", () => toggleSpeech(ttsButton, speakText));

  return card;
}

let activeSpeechButton = null;

function toggleSpeech(button, text) {
  if (!("speechSynthesis" in window)) {
    alert("이 브라우저는 음성 듣기(TTS)를 지원하지 않습니다.");
    return;
  }

  if (activeSpeechButton === button) {
    stopSpeech();
    return;
  }

  window.speechSynthesis.cancel();
  if (activeSpeechButton) resetSpeechButton(activeSpeechButton);

  const utterance = new SpeechSynthesisUtterance(text || "내용이 없습니다.");
  utterance.lang = "ko-KR";
  utterance.onend = () => {
    if (activeSpeechButton === button) {
      resetSpeechButton(button);
      activeSpeechButton = null;
    }
  };
  utterance.onerror = () => {
    if (activeSpeechButton === button) {
      resetSpeechButton(button);
      activeSpeechButton = null;
    }
  };

  button.textContent = "⏸";
  button.classList.add("is-speaking");
  activeSpeechButton = button;
  window.speechSynthesis.speak(utterance);
}

function stopSpeech() {
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  if (activeSpeechButton) resetSpeechButton(activeSpeechButton);
  activeSpeechButton = null;
}

function resetSpeechButton(button) {
  button.textContent = "🔊";
  button.classList.remove("is-speaking");
}

function renderQuoteList(data) {
  els.content.innerHTML = "";

  if (data.failed_symbols && data.failed_symbols.length > 0) {
    const note = document.createElement("div");
    note.className = "failed-note";
    note.textContent = `Some symbols could not be loaded: ${data.failed_symbols.join(", ")}`;
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
    <div class="symbol" style="margin-top:6px;">${escapeHtml(quote.trust?.provider || "공급자 미확인")} · ${quote.trust?.is_delayed ? "지연 시세" : "실시간"} · ${escapeHtml(quote.trust?.currency || "통화 미확인")} · ${quote.trust?.reference_at ? new Date(quote.trust.reference_at).toLocaleString("ko-KR") : "기준시각 없음"}</div>
  `;
  return item;
}

async function openDetail(symbol) {
  els.modalBackdrop.classList.remove("hidden");
  els.modalBody.innerHTML = '<div class="loading">Loading detail...</div>';

  try {
    const res = await fetch(`/stock/api/quotes/${encodeURIComponent(symbol)}?market=${state.selectedMarket}`);
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
      <div style="display:flex;gap:8px;margin-top:10px;"><button id="watchlist-btn">☆ 관심종목</button><button id="price-alert-btn">가격/등락률 알림</button></div>
    </div>
    <div class="chart-card">
      <h3>가격·거래량 차트</h3>
      <div style="display:flex;gap:6px;margin-bottom:8px;">${[["1d","일"],["5d","주"],["1mo","월"],["1y","1년"],["5y","5년"]].map(([value,label]) => `<button class="period-btn" data-period="${value}">${label}</button>`).join("")}</div>
      <canvas id="price-chart"></canvas>
    </div>
    <div class="info-grid">
      ${infoCell("Exchange", quote.exchange_name || "-")}
      ${infoCell("Currency", quote.currency || "-")}
      ${infoCell("Open", quote.open_price != null ? formatNumber(quote.open_price, quote.currency) : "-")}
      ${infoCell("High", quote.day_high != null ? formatNumber(quote.day_high, quote.currency) : "-")}
      ${infoCell("Low", quote.day_low != null ? formatNumber(quote.day_low, quote.currency) : "-")}
      ${infoCell("Updated", quote.market_time ? formatDateTime(quote.market_time) : "-")}
      ${infoCell("Provider", quote.trust?.provider || "-")}
      ${infoCell("Delay", quote.trust?.delay_note || "-")}
      ${infoCell("52-week", quote.fifty_two_week_low != null ? `${formatNumber(quote.fifty_two_week_low, quote.currency)} ~ ${formatNumber(quote.fifty_two_week_high, quote.currency)}` : "-")}
      ${infoCell("Market cap", quote.market_cap != null ? Number(quote.market_cap).toLocaleString() : "-")}
      ${infoCell("PER / PBR", `${quote.trailing_pe ?? "-"} / ${quote.price_to_book ?? "-"}`)}
      ${infoCell("Regular / Pre / After", `${quote.session_prices?.regular ?? "-"} / ${quote.session_prices?.pre_market ?? "-"} / ${quote.session_prices?.after_market ?? "-"}`)}
    </div>
    <div class="chart-card"><h3>매출·영업이익 추세</h3>${(quote.financial_trends || []).length ? `<table style="width:100%"><tr><th>기간</th><th>매출</th><th>영업이익</th></tr>${quote.financial_trends.map(row => `<tr><td>${escapeHtml(row.period)}</td><td>${row.revenue != null ? Number(row.revenue).toLocaleString() : "-"}</td><td>${row.operating_income != null ? Number(row.operating_income).toLocaleString() : "-"}</td></tr>`).join("")}</table>` : "공급자 재무 데이터가 없습니다."}</div>
    <div class="ai-card" id="ai-card">
      <h3>AI analysis</h3>
      <button class="ai-btn" id="ai-btn">Run AI analysis</button>
      <div id="ai-output"></div>
    </div>
    <div class="chart-card" id="context-card"><h3>이벤트·뉴스</h3><div class="loading">출처 정보를 불러오는 중...</div></div>
  `;

  renderChart(quote.chart_points);
  document.querySelectorAll(".period-btn").forEach(button => button.addEventListener("click", () => reloadDetailPeriod(quote.symbol, button.dataset.period)));
  document.getElementById("ai-btn").addEventListener("click", () => loadAiAnalysis(quote.symbol));
  document.getElementById("watchlist-btn").addEventListener("click", () => saveWatchlist(quote));
  document.getElementById("price-alert-btn").addEventListener("click", () => createAlert(quote));
  loadStockContext(quote.symbol);
}

async function saveWatchlist(quote) {
  const res = await fetch("/stock/api/watchlist", {method:"POST",headers:{"Content-Type":"application/json",...csrfHeaders()},body:JSON.stringify({symbol:quote.symbol,name:quote.short_name})});
  alert(res.ok ? "관심종목에 저장했습니다." : "로그인 후 관심종목을 저장할 수 있습니다.");
}

async function createAlert(quote) {
  const threshold = prompt("알림 받을 가격을 입력하세요", String(quote.price));
  if (!threshold) return;
  const res = await fetch("/stock/api/alerts", {method:"POST",headers:{"Content-Type":"application/json",...csrfHeaders()},body:JSON.stringify({symbol:quote.symbol,condition:"above",threshold:Number(threshold)})});
  alert(res.ok ? "가격 알림을 저장했습니다." : "로그인 후 알림을 설정할 수 있습니다.");
}

async function loadStockContext(symbol) {
  const target = document.getElementById("context-card");
  const res = await fetch(`/stock/api/quotes/${encodeURIComponent(symbol)}/context`);
  if (!res.ok || !target) return;
  const data = await res.json();
  target.innerHTML = `<h3>이벤트·뉴스</h3>${(data.events || []).map(e => `<p><strong>${escapeHtml(e.title)}</strong> · ${new Date(e.at).toLocaleDateString("ko-KR")} ${e.estimated ? "(예정·확인 필요)" : ""}<br><a href="${escapeHtml(e.source.url)}" target="_blank" rel="noreferrer">출처: ${escapeHtml(e.source.name)}</a></p>`).join("") || "등록된 일정이 없습니다."}${(data.news || []).map(n => `<p><strong>${escapeHtml(n.title)}</strong><br>사실: ${escapeHtml(n.factSummary)}<br>시장 해석: ${escapeHtml(n.marketInterpretation || "별도 해석 없음")}<br><a href="${escapeHtml(n.source.url)}" target="_blank" rel="noreferrer">${escapeHtml(n.source.name)}</a></p>`).join("")}`;
}

async function reloadDetailPeriod(symbol, period) {
  const res = await fetch(`/stock/api/quotes/${encodeURIComponent(symbol)}?market=${state.selectedMarket}&period=${period}`);
  if (!res.ok) return;
  renderDetail(await res.json());
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
    ctx.replaceWith(document.createTextNode("No chart data."));
    return;
  }

  state.chart = new Chart(ctx, {
    type: "line",
    data: {
      labels: points.map((point) => new Date(point.timestamp * 1000).toLocaleDateString()),
      datasets: [
        {
          label: "가격",
          data: points.map((point) => point.close),
          borderColor: "#2563eb",
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.2,
        },
        {
          type: "bar", label: "거래량", data: points.map((point) => point.volume),
          backgroundColor: "rgba(100,116,139,.22)", yAxisID: "volume", borderWidth: 0,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { display: false },
        y: { display: true },
        volume: { display: false, position: "right", grid: { drawOnChartArea: false } },
      },
    },
  });
}

async function loadAiAnalysis(symbol) {
  const btn = document.getElementById("ai-btn");
  const output = document.getElementById("ai-output");
  btn.disabled = true;
  output.innerHTML = '<div class="loading">AI is analyzing...</div>';

  try {
    const res = await fetch(`/stock/api/quotes/${encodeURIComponent(symbol)}/analysis?market=${state.selectedMarket}`);
    const data = await res.json();
    if (!data.available) {
      output.innerHTML = '<div class="ai-disabled">AI analysis is disabled because no API key is configured.</div>';
    } else if (data.error) {
      const modelsList =
        data.available_models && data.available_models.length > 0
          ? `<div class="ai-models-label">Available models for ${data.provider || "-"}:</div>
             <ul class="ai-models-list">${data.available_models.map((model) => `<li>${escapeHtml(model)}</li>`).join("")}</ul>`
          : '<div class="ai-models-label">No available models were returned.</div>';
      output.innerHTML = `
        <div class="status">AI analysis failed (${data.provider || "-"}): ${escapeHtml(data.error)}</div>
        ${modelsList}
      `;
    } else {
      output.innerHTML = `<div class="ai-text" style="white-space:pre-wrap">${escapeHtml(data.analysis || "No analysis result.")}</div><small>화면 대조 완료: ${data.verified_against_quote ? "예" : "아니오"} · 근거 현재가 ${escapeHtml(data.evidence?.price)} ${escapeHtml(data.evidence?.currency)} · ${escapeHtml(data.evidence?.period)}</small>`;
    }
  } catch (err) {
    output.innerHTML = '<div class="status">Could not load AI analysis.</div>';
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
