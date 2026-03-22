// App shell behaviors: service worker, toast, and swipe navigation.

(function registerServiceWorker() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/static/sw.js");
  }
})();

(function pushNotificationsBootstrap() {
  const body = document.body;
  const userId = String((body && body.dataset && body.dataset.userId) || "").trim();
  if (!userId) return;
  if (!("serviceWorker" in navigator) || !("Notification" in window)) return;

  const csrf = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';

  function base64UrlToUint8Array(base64String) {
    const pad = '='.repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + pad).replace(/-/g, '+').replace(/_/g, '/');
    const raw = window.atob(base64);
    const output = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i += 1) output[i] = raw.charCodeAt(i);
    return output;
  }

  async function fetchPushConfig() {
    const res = await fetch('/notifications/push/config', { credentials: 'same-origin' });
    if (!res.ok) return null;
    const data = await res.json().catch(() => null);
    return data?.push || null;
  }

  async function saveWebPushSubscription(subscription) {
    await fetch('/notifications/push/subscribe', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': csrf,
      },
      body: JSON.stringify({ subscription }),
    });
  }

  async function saveFcmToken(token) {
    await fetch('/notifications/push/fcm/register', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': csrf,
      },
      body: JSON.stringify({ token }),
    });
  }

  async function ensureWebPushSubscription(pushCfg) {
    if (!("PushManager" in window) || !pushCfg.vapid_public_key) return;
    const reg = await navigator.serviceWorker.ready;
    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: base64UrlToUint8Array(pushCfg.vapid_public_key),
      });
    }
    if (sub) {
      const subJson = sub.toJSON();
      const endpoint = String((subJson || {}).endpoint || '');
      const cacheKey = 'ft-push-endpoint-v1';
      const savedEndpoint = localStorage.getItem(cacheKey) || '';
      if (endpoint && endpoint !== savedEndpoint) {
        await saveWebPushSubscription(subJson);
        localStorage.setItem(cacheKey, endpoint);
      }
    }
  }

  async function ensureFirebaseToken(pushCfg) {
    const firebaseConfig = pushCfg?.firebase_config || {};
    const required = ['apiKey', 'projectId', 'messagingSenderId', 'appId'];
    if (!required.every((k) => String(firebaseConfig[k] || '').trim())) {
      return;
    }
    if (!pushCfg.vapid_public_key) return;

    const [{ initializeApp }, { getMessaging, getToken }] = await Promise.all([
      import('https://www.gstatic.com/firebasejs/12.10.0/firebase-app.js'),
      import('https://www.gstatic.com/firebasejs/12.10.0/firebase-messaging.js'),
    ]);

    const app = initializeApp(firebaseConfig, 'fintrack-push');
    const messaging = getMessaging(app);
    const reg = await navigator.serviceWorker.ready;
    const token = await getToken(messaging, {
      vapidKey: pushCfg.vapid_public_key,
      serviceWorkerRegistration: reg,
    });

    if (!token) return;
    const cacheKey = 'ft-fcm-token-v1';
    const savedToken = localStorage.getItem(cacheKey) || '';
    if (token !== savedToken) {
      await saveFcmToken(token);
      localStorage.setItem(cacheKey, token);
    }
  }

  async function ensurePushSubscription() {
    try {
      const pushCfg = await fetchPushConfig();
      if (!pushCfg || !pushCfg.enabled) return;

      let permission = Notification.permission;
      if (permission === 'default') {
        permission = await Notification.requestPermission();
      }
      if (permission !== 'granted') return;

      const provider = String(pushCfg.provider || 'webpush').toLowerCase();
      if (provider === 'firebase') {
        await ensureFirebaseToken(pushCfg);
      } else {
        await ensureWebPushSubscription(pushCfg);
      }
    } catch (err) {
      console.warn('Push bootstrap failed:', err);
    }
  }

  navigator.serviceWorker.addEventListener('message', (event) => {
    const data = (event && event.data) || {};
    if (data.type !== 'ft-open-url') return;
    if (data.url) window.location.href = String(data.url);
  });

  ensurePushSubscription();
})();

(function themeMode() {
  const key = "ft-theme-mode";
  const root = document.documentElement;
  const metaTheme = document.querySelector('meta[name="theme-color"]');
  const toggleButtons = document.querySelectorAll("[data-theme-toggle]");
  const icons = document.querySelectorAll("[data-theme-icon]");
  const media = window.matchMedia("(prefers-color-scheme: dark)");

  function setButtonState(mode) {
    const isDark = mode === "dark";
    toggleButtons.forEach((btn) => {
      btn.setAttribute("aria-label", isDark ? "Switch to light mode" : "Switch to dark mode");
      btn.setAttribute("title", isDark ? "Switch to light mode" : "Switch to dark mode");
    });
    icons.forEach((icon) => {
      icon.className = isDark ? "fa-solid fa-sun" : "fa-solid fa-moon";
    });
  }

  function applyMode(mode) {
    root.setAttribute("data-theme", mode);
    setButtonState(mode);
    if (metaTheme) {
      metaTheme.setAttribute("content", mode === "dark" ? "#060b16" : "#0f172a");
    }
  }

  const saved = localStorage.getItem(key);
  const initial = saved === "dark" || saved === "light"
    ? saved
    : (media.matches ? "dark" : "light");
  applyMode(initial);

  toggleButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      localStorage.setItem(key, next);
      applyMode(next);
    });
  });

  media.addEventListener("change", (event) => {
    const stored = localStorage.getItem(key);
    if (stored === "dark" || stored === "light") return;
    applyMode(event.matches ? "dark" : "light");
  });
})();

(function toastMessages() {
  const toast = document.getElementById("toast");
  if (!toast) return;
  const messageEl = toast.querySelector(".toast-message");
  const closeBtn = toast.querySelector(".toast-close");
  const iconEl = toast.querySelector(".toast-icon");
  let hideTimer = null;

  function hide() {
    toast.classList.remove("show");
    toast.classList.remove("toast-success", "toast-error", "toast-info");
    if (hideTimer) {
      window.clearTimeout(hideTimer);
      hideTimer = null;
    }
  }

  function show(message, kind = "error") {
    const msg = String(message || "").trim();
    if (!msg) return;
    const mode = ["success", "error", "info"].includes(kind) ? kind : "error";
    messageEl.textContent = msg;
    toast.classList.remove("toast-success", "toast-error", "toast-info");
    toast.classList.add(`toast-${mode}`);
    if (iconEl) {
      iconEl.textContent = mode === "success" ? "✓" : mode === "info" ? "i" : "!";
    }
    toast.classList.add("show");
    if (hideTimer) window.clearTimeout(hideTimer);
    hideTimer = window.setTimeout(hide, 5000);
  }

  window.ftNotify = show;
  if (closeBtn) closeBtn.addEventListener("click", hide);

  const msgRaw = (toast.dataset.error || "").trim();
  const msg = (msgRaw === "None" || msgRaw === "null") ? "" : msgRaw;
  if (msg) show(msg, "error");

  const url = new URL(window.location.href);
  const auth = (url.searchParams.get("auth") || "").toLowerCase();
  if (auth) {
    const errorCode = (url.searchParams.get("error") || "").toLowerCase();
    if (auth === "success") {
      show("Authentication successful.", "success");
    } else if (auth === "failed") {
      let message = "Authentication failed.";
      if (errorCode === "invalid") message = "Authentication failed: invalid credentials.";
      if (errorCode === "oauth_state") message = "Authentication failed: invalid OAuth state.";
      if (errorCode === "oauth_token") message = "Authentication failed: token exchange failed.";
      show(message, "error");
    }
    url.searchParams.delete("auth");
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  }
})();

(function maintenanceReadonlyMode() {
  const body = document.body;
  if (!body) return;
  const maintenanceMode = String(body.dataset.maintenanceMode || "").toLowerCase() === "true";
  if (!maintenanceMode) return;

  function isAuthFormControl(el) {
    const form = el.closest("form");
    if (!form) return false;
    if (form.classList.contains("login-form")) return true;
    const action = String(form.getAttribute("action") || "").toLowerCase();
    return action.includes("/login") || action.includes("/reset-password");
  }

  const root = document.querySelector(".app-content") || document;
  const controls = root.querySelectorAll("input, textarea, select, button");
  controls.forEach((el) => {
    if (!(el instanceof HTMLElement)) return;
    if (el.hasAttribute("data-maintenance-allowed")) return;
    if (isAuthFormControl(el)) return;
    const type = (el.getAttribute("type") || "").toLowerCase();
    if (type === "hidden") return;

    if (el instanceof HTMLInputElement) {
      if (["checkbox", "radio", "file", "submit", "button", "reset"].includes(type)) {
        el.disabled = true;
        el.setAttribute("aria-disabled", "true");
      } else {
        el.readOnly = true;
        el.setAttribute("readonly", "readonly");
        el.setAttribute("aria-readonly", "true");
      }
      return;
    }
    if (el instanceof HTMLTextAreaElement) {
      el.readOnly = true;
      el.setAttribute("readonly", "readonly");
      el.setAttribute("aria-readonly", "true");
      return;
    }
    if (el instanceof HTMLSelectElement) {
      el.disabled = true;
      el.setAttribute("aria-disabled", "true");
      return;
    }
    if (el instanceof HTMLButtonElement) {
      el.disabled = true;
      el.setAttribute("aria-disabled", "true");
    }
  });
})();

(function swipeNavigation() {
  const isMobile = () => window.matchMedia("(max-width: 768px)").matches;
  const pages = ["/", "/transactions", "/transactions/list", "/recurring", "/accounts", "__profile__"];
  const appShell = document.querySelector(".app-shell");

  let startX = 0;
  let startY = 0;
  let lastDx = 0;
  let trackingIndex = 0;
  let tracking = false;
  let dragging = false;
  let navigating = false;
  let axisLocked = false;
  let horizontalAxis = false;

  function setShellTransform(dxPx) {
    if (!appShell) return;
    const width = Math.max(window.innerWidth || 1, 1);
    const distance = Math.abs(dxPx);
    const opacity = Math.max(0.84, 1 - (distance / width) * 0.16);
    appShell.style.transform = `translateX(${dxPx}px)`;
    appShell.style.opacity = String(opacity);
  }

  function resetShell() {
    if (!appShell) return;
    appShell.classList.remove("swipe-dragging");
    appShell.style.transform = "";
    appShell.style.opacity = "";
  }

  function openProfileMenu() {
    const toggles = Array.from(document.querySelectorAll("[data-profile-toggle]"));
    const visibleToggle = toggles.find((btn) => {
      const rect = btn.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    });
    if (visibleToggle) visibleToggle.click();
  }

  function canMove(dx, idx) {
    if (dx < 0) return idx < pages.length - 1;
    if (dx > 0) return idx > 0;
    return true;
  }

  function currentIndex() {
    const path = window.location.pathname;
    if (path === "/") return 0;
    const matches = pages
      .map((p, i) => ({ p, i }))
      .filter((item) => item.p !== "/" && path.startsWith(item.p))
      .sort((a, b) => b.p.length - a.p.length);
    return matches.length ? matches[0].i : 0;
  }

  function onTouchStart(e) {
    if (!isMobile() || navigating) return;
    if (!e.touches || e.touches.length !== 1) return;
    const target = e.target;
    if (target && target.closest("input, textarea, select, button, a")) return;
    tracking = true;
    dragging = false;
    axisLocked = false;
    horizontalAxis = false;
    startX = e.touches[0].clientX;
    startY = e.touches[0].clientY;
    lastDx = 0;
    trackingIndex = currentIndex();
  }

  function onTouchMove(e) {
    if (!tracking || !isMobile() || navigating) return;
    if (!e.touches || e.touches.length !== 1) return;
    const dxRaw = e.touches[0].clientX - startX;
    const dyRaw = e.touches[0].clientY - startY;

    if (!axisLocked) {
      if (Math.abs(dxRaw) < 8 && Math.abs(dyRaw) < 8) return;
      axisLocked = true;
      horizontalAxis = Math.abs(dxRaw) > Math.abs(dyRaw) * 1.15;
      if (!horizontalAxis) {
        tracking = false;
        return;
      }
    }

    if (!horizontalAxis) return;
    const allowed = canMove(dxRaw, trackingIndex);
    const resistance = allowed ? 0.5 : 0.18;
    const dx = dxRaw * resistance;
    lastDx = dxRaw;
    dragging = true;
    if (appShell) appShell.classList.add("swipe-dragging");
    setShellTransform(dx);
    e.preventDefault();
  }

  function onTouchEnd() {
    if (!tracking || !isMobile()) return;
    tracking = false;
    if (!dragging) {
      resetShell();
      return;
    }

    const commitThreshold = Math.min(120, Math.round(window.innerWidth * 0.18));
    const idx = trackingIndex;
    const dir = lastDx < 0 ? -1 : 1;
    const nextIdx = dir < 0 ? idx + 1 : idx - 1;
    const canCommit = Math.abs(lastDx) >= commitThreshold && nextIdx >= 0 && nextIdx < pages.length;

    if (!canCommit) {
      resetShell();
      dragging = false;
      return;
    }

    navigating = true;
    dragging = false;
    const target = pages[nextIdx];
    const width = Math.max(window.innerWidth || 1, 1);
    const finalShift = (dir < 0 ? -1 : 1) * Math.round(width * 0.5);

    if (appShell) appShell.classList.remove("swipe-dragging");
    setShellTransform(finalShift);

    const prefersReduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const delay = prefersReduce ? 0 : 220;
    setTimeout(() => {
      if (target === "__profile__") {
        openProfileMenu();
        resetShell();
        navigating = false;
        return;
      }
      window.location.href = target;
    }, delay);
  }

  function onTouchCancel() {
    tracking = false;
    dragging = false;
    resetShell();
  }

  document.addEventListener("touchstart", onTouchStart, { passive: true });
  document.addEventListener("touchmove", onTouchMove, { passive: false });
  document.addEventListener("touchend", onTouchEnd, { passive: true });
  document.addEventListener("touchcancel", onTouchCancel, { passive: true });
})();
