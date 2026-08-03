// AiStockQuote 회원 인증(회원가입/로그인/비밀번호 찾기·변경) 클라이언트 로직.
// 기존 app.js(시세/AI 분석)와 완전히 분리된 파일로 둬서 이 기능을 추가하며
// app.js를 건드릴 필요가 없게 했습니다. index.html이 이 파일을 app.js 다음에
// 별도 <script>로 불러옵니다.

(function () {
  "use strict";

  const API_BASE = "/stock/api/auth";

  function qs(id) {
    return document.getElementById(id);
  }

  async function postJson(url, body) {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    let data = {};
    try {
      data = await response.json();
    } catch (error) {
      data = { ok: false, error: "서버 응답을 해석할 수 없습니다." };
    }
    return { ok: response.ok, status: response.status, data: data };
  }

  async function getJson(url) {
    const response = await fetch(url);
    const data = await response.json();
    return { ok: response.ok, data: data };
  }

  function openModal(id) {
    closeAllModals();
    const el = qs(id);
    if (el) el.classList.remove("auth-hidden");
  }

  function closeAllModals() {
    document.querySelectorAll(".auth-modal-backdrop").forEach((el) => el.classList.add("auth-hidden"));
  }

  function setStatus(id, message, isError) {
    const el = qs(id);
    if (!el) return;
    el.textContent = message || "";
    el.className = "auth-status" + (isError ? " auth-status-error" : message ? " auth-status-ok" : "");
  }

  // 2026-07-22: 회원가입 동의 항목(ConsentItem) -- 이용약관/개인정보처리방침/
  // AI 서비스 이용안내(필수), 마케팅수신동의/위치정보이용약관(선택). 기존
  // "개인정보 수집·이용 동의" 단일 체크박스는 "개인정보처리방침" 항목으로 흡수됐다.
  let consentItems = [];

  async function loadConsentItems() {
    try {
      const result = await getJson("/stock/api/consent-items/active/");
      consentItems = (result.data && result.data.items) || [];
    } catch (error) {
      consentItems = [];
    }
    renderConsentItems();
  }

  function renderConsentItems() {
    const container = qs("consentItemsContainer");
    if (!container) return;
    container.innerHTML = "";
    consentItems.forEach((item) => {
      const box = document.createElement("div");
      box.className = "consent-terms-box";
      box.innerHTML = "<h4>" + (item.titleKo || item.label) + "</h4><pre>" + (item.bodyKo || "").replace(/</g, "&lt;") + "</pre>";

      const row = document.createElement("div");
      row.className = "auth-checkbox-row";
      row.innerHTML =
        '<input type="checkbox" data-consent-key="' + item.key + '" id="consent_' + item.key + '" ' + (item.isRequired ? "required" : "") + '>' +
        '<label for="consent_' + item.key + '">' + item.label + " (" + (item.isRequired ? "필수" : "선택") + ")</label>";
      container.appendChild(box);
      container.appendChild(row);
    });
  }

  function collectConsents() {
    const consents = {};
    document.querySelectorAll("#consentItemsContainer [data-consent-key]").forEach((input) => {
      consents[input.getAttribute("data-consent-key")] = input.checked;
    });
    return consents;
  }

  function firstMissingRequiredConsentLabel(consents) {
    for (let i = 0; i < consentItems.length; i++) {
      const item = consentItems[i];
      if (item.isRequired && !consents[item.key]) return item.label;
    }
    return null;
  }

  function openPostcodeSearch(prefix) {
    if (typeof daum === "undefined" || !daum.Postcode) {
      alert("우편번호 검색 스크립트를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.");
      return;
    }
    new daum.Postcode({
      oncomplete: function (data) {
        const postal = qs(prefix + "PostalCode");
        const road = qs(prefix + "RoadAddress");
        const detail = qs(prefix + "AddressDetail");
        if (postal) postal.value = data.zonecode;
        if (road) road.value = data.roadAddress || data.jibunAddress;
        if (detail) detail.focus();
      },
    }).open();
  }

  function renderAuthBar(member) {
    const bar = qs("authBar");
    if (!bar) return;
    if (member) {
      bar.innerHTML =
        '<span class="auth-bar-name">' + member.name + '님</span>' +
        '<button type="button" id="authChangePwBtn" class="auth-bar-btn">비밀번호 변경</button>' +
        '<button type="button" id="authLogoutBtn" class="auth-bar-btn">로그아웃</button>';
      qs("authChangePwBtn").addEventListener("click", () => openModal("changePasswordModal"));
      qs("authLogoutBtn").addEventListener("click", handleLogout);
    } else {
      bar.innerHTML =
        '<button type="button" id="authLoginBtn" class="auth-bar-btn">로그인</button>' +
        '<button type="button" id="authSignupBtn" class="auth-bar-btn auth-bar-btn-primary">회원가입</button>';
      // 2026-07-23: 로그인/회원가입을 독립 페이지로 분리 -- 이 두 버튼만
      // 새 페이지로 이동시킨다(비밀번호 변경 모달 등 나머지는 그대로 둔다).
      qs("authLoginBtn").addEventListener("click", () => { window.location.href = "/stock/login/"; });
      qs("authSignupBtn").addEventListener("click", () => { window.location.href = "/stock/signup/"; });
    }
  }

  async function refreshAuthState() {
    const result = await getJson(API_BASE + "/me/");
    renderAuthBar(result.data && result.data.authenticated ? result.data.member : null);
    return result.data;
  }

  async function handleLogout() {
    await postJson(API_BASE + "/logout/", {});
    await refreshAuthState();
  }

  async function handleSignup(event) {
    event.preventDefault();
    const consents = collectConsents();
    const missingConsentLabel = firstMissingRequiredConsentLabel(consents);
    if (missingConsentLabel) {
      setStatus("signupStatus", missingConsentLabel + " 동의가 필요합니다.", true);
      return;
    }
    setStatus("signupStatus", "가입 처리 중입니다...", false);
    const payload = {
      email: qs("signupEmail").value.trim(),
      name: qs("signupName").value.trim(),
      password: qs("signupPassword").value,
      passwordConfirm: qs("signupPasswordConfirm").value,
      phone: qs("signupPhone").value.trim(),
      postalCode: qs("signupPostalCode").value.trim(),
      roadAddress: qs("signupRoadAddress").value.trim(),
      addressDetail: qs("signupAddressDetail").value.trim(),
      consents: consents,
    };
    const result = await postJson(API_BASE + "/signup/", payload);
    if (!result.ok) {
      setStatus("signupStatus", (result.data && result.data.error) || "가입에 실패했습니다.", true);
      return;
    }
    setStatus(
      "signupStatus",
      "가입이 완료되었습니다. 이메일로 발송된 인증 링크를 눌러 인증을 완료해 주세요.",
      false
    );
    qs("signupForm").reset();
  }

  async function handleLogin(event) {
    event.preventDefault();
    setStatus("loginStatus", "로그인 중입니다...", false);
    const payload = { email: qs("loginEmail").value.trim(), password: qs("loginPassword").value };
    const result = await postJson(API_BASE + "/login/", payload);
    if (!result.ok) {
      setStatus("loginStatus", (result.data && result.data.error) || "로그인에 실패했습니다.", true);
      return;
    }
    qs("loginForm").reset();
    closeAllModals();
    await refreshAuthState();
  }

  async function handleForgotPassword(event) {
    event.preventDefault();
    setStatus("forgotStatus", "요청을 처리하는 중입니다...", false);
    const payload = { email: qs("forgotEmail").value.trim() };
    const result = await postJson(API_BASE + "/forgot/", payload);
    setStatus(
      "forgotStatus",
      (result.data && result.data.message) || "요청을 처리했습니다.",
      !result.ok
    );
  }

  async function handleResetPassword(event) {
    event.preventDefault();
    setStatus("resetStatus", "비밀번호를 변경하는 중입니다...", false);
    const payload = {
      token: qs("resetToken").value,
      password: qs("resetPassword").value,
      passwordConfirm: qs("resetPasswordConfirm").value,
    };
    const result = await postJson(API_BASE + "/reset/", payload);
    if (!result.ok) {
      setStatus("resetStatus", (result.data && result.data.error) || "비밀번호 변경에 실패했습니다.", true);
      return;
    }
    setStatus("resetStatus", "비밀번호가 변경되었습니다. 이제 로그인해 주세요.", false);
    qs("resetPasswordForm").reset();
    setTimeout(() => openModal("loginModal"), 1200);
  }

  async function handleChangePassword(event) {
    event.preventDefault();
    setStatus("changePwStatus", "변경하는 중입니다...", false);
    const payload = {
      currentPassword: qs("changePwCurrent").value,
      newPassword: qs("changePwNew").value,
      newPasswordConfirm: qs("changePwNewConfirm").value,
    };
    const result = await postJson(API_BASE + "/change-password/", payload);
    if (!result.ok) {
      setStatus("changePwStatus", (result.data && result.data.error) || "비밀번호 변경에 실패했습니다.", true);
      return;
    }
    setStatus("changePwStatus", "비밀번호가 변경되었습니다.", false);
    qs("changePasswordForm").reset();
  }

  const SOCIAL_PROVIDER_LABELS = { kakao: "카카오", naver: "네이버", google: "구글", apple: "애플" };

  function renderSocialButtons() {
    const providers = window.STOCK_SOCIAL_PROVIDERS || [];
    if (!providers.length) return;

    const buttonsHtml = providers
      .map((provider) => {
        return (
          '<button type="button" class="social-auth-btn social-auth-' + provider + '" data-social-provider="' +
          provider + '">' + (SOCIAL_PROVIDER_LABELS[provider] || provider) + '로 계속하기</button>'
        );
      })
      .join("");

    const signupForm = qs("signupForm");
    if (signupForm) {
      const wrap = document.createElement("div");
      wrap.innerHTML =
        '<div class="social-auth-divider">또는 소셜 계정으로 계속하기</div>' +
        '<div class="social-auth-row" data-social-mode="signup">' + buttonsHtml + '</div>' +
        '<p style="font-size:0.75rem;color:#888;margin-top:8px;">소셜 가입도 위 필수 약관/동의 항목에 먼저 동의해야 합니다.</p>';
      signupForm.appendChild(wrap);
    }

    const loginForm = qs("loginForm");
    if (loginForm) {
      const wrap = document.createElement("div");
      wrap.innerHTML =
        '<div class="social-auth-divider">또는 소셜 계정으로 계속하기</div>' +
        '<div class="social-auth-row" data-social-mode="login">' + buttonsHtml + '</div>';
      loginForm.appendChild(wrap);
    }

    document.querySelectorAll(".social-auth-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const provider = btn.getAttribute("data-social-provider");
        const mode = btn.closest(".social-auth-row").getAttribute("data-social-mode");
        const params = new URLSearchParams();
        params.set("next", "/stock/");
        if (mode === "signup") {
          const consents = collectConsents();
          const missingConsentLabel = firstMissingRequiredConsentLabel(consents);
          if (missingConsentLabel) {
            setStatus("signupStatus", "필수 약관/동의 항목에 모두 동의해 주세요.", true);
            return;
          }
          params.set("consents", JSON.stringify(consents));
        }
        window.location.href = "/stock/api/auth/social/" + provider + "/start/?" + params.toString();
      });
    });
  }

  function handleSocialAuthRedirectResult() {
    const params = new URLSearchParams(window.location.search);
    const success = params.get("social");
    const error = params.get("socialError");
    if (!success && !error) return;

    if (success === "success") {
      refreshAuthState();
    } else if (error) {
      openModal("loginModal");
      setStatus("loginStatus", decodeURIComponent(error) || "소셜 로그인에 실패했습니다.", true);
    }

    params.delete("social");
    params.delete("socialError");
    const newSearch = params.toString();
    const newUrl = window.location.pathname + (newSearch ? "?" + newSearch : "");
    window.history.replaceState({}, "", newUrl);
  }

  function openResetModalFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const token = params.get("resetToken");
    if (!token) return;
    qs("resetToken").value = token;
    openModal("resetPasswordModal");
    params.delete("resetToken");
    const newSearch = params.toString();
    const newUrl = window.location.pathname + (newSearch ? "?" + newSearch : "");
    window.history.replaceState({}, "", newUrl);
  }

  function wireUp() {
    document.querySelectorAll(".auth-modal-close").forEach((btn) => {
      btn.addEventListener("click", closeAllModals);
    });
    document.querySelectorAll(".auth-modal-backdrop").forEach((backdrop) => {
      backdrop.addEventListener("click", (event) => {
        if (event.target === backdrop) closeAllModals();
      });
    });
    document.querySelectorAll(".auth-postcode-btn").forEach((btn) => {
      btn.addEventListener("click", () => openPostcodeSearch(btn.getAttribute("data-prefix")));
    });

    qs("signupForm").addEventListener("submit", handleSignup);
    qs("loginForm").addEventListener("submit", handleLogin);
    qs("forgotPasswordForm").addEventListener("submit", handleForgotPassword);
    qs("resetPasswordForm").addEventListener("submit", handleResetPassword);
    qs("changePasswordForm").addEventListener("submit", handleChangePassword);

    qs("showForgotLink").addEventListener("click", (event) => {
      event.preventDefault();
      openModal("forgotPasswordModal");
    });
    qs("showSignupFromLogin").addEventListener("click", (event) => {
      event.preventDefault();
      openModal("signupModal");
    });
    qs("showLoginFromSignup").addEventListener("click", (event) => {
      event.preventDefault();
      openModal("loginModal");
    });
    qs("resendVerificationLink").addEventListener("click", async (event) => {
      event.preventDefault();
      const email = (qs("loginEmail").value || "").trim();
      if (!email) {
        alert("먼저 이메일을 입력해 주세요.");
        return;
      }
      await postJson(API_BASE + "/resend/", { email: email });
      alert("해당 이메일이 등록되어 있다면 인증 메일을 다시 보냈습니다.");
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    wireUp();
    renderSocialButtons();
    refreshAuthState();
    loadConsentItems();
    openResetModalFromUrl();
    handleSocialAuthRedirectResult();
  });
})();
