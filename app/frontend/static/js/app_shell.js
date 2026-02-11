// App shell behaviors: service worker, toast, and swipe navigation.

(function registerServiceWorker() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/static/sw.js");
  }
})();

(function toastMessages() {
  const toast = document.getElementById("toast");
  if (!toast) return;
  const msg = toast.dataset.error || "";
  if (!msg) return;
  const messageEl = toast.querySelector(".toast-message");
  const closeBtn = toast.querySelector(".toast-close");
  messageEl.textContent = msg;
  toast.classList.add("show");
  const hide = () => toast.classList.remove("show");
  if (closeBtn) closeBtn.addEventListener("click", hide);
  setTimeout(hide, 5000);
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
