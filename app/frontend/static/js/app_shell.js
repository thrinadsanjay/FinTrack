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
  const pages = ["/", "/transactions", "/transactions/list", "/accounts", "__profile__"];

  let startX = 0;
  let startY = 0;
  let tracking = false;
  let navigating = false;

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
    if (!isMobile()) return;
    if (!e.touches || e.touches.length !== 1) return;
    const target = e.target;
    if (target && target.closest("input, textarea, select, button, a")) return;
    tracking = true;
    startX = e.touches[0].clientX;
    startY = e.touches[0].clientY;
  }

  function onTouchEnd(e) {
    if (!tracking || !isMobile()) return;
    tracking = false;
    if (!e.changedTouches || e.changedTouches.length !== 1) return;
    const dx = e.changedTouches[0].clientX - startX;
    const dy = e.changedTouches[0].clientY - startY;
    if (Math.abs(dx) < 60 || Math.abs(dx) < Math.abs(dy) * 1.5) return;

    const idx = currentIndex();
    const nextIdx = dx < 0 ? idx + 1 : idx - 1;
    if (nextIdx < 0 || nextIdx >= pages.length) return;
    if (navigating) return;
    navigating = true;
    const dirClass = dx < 0 ? "page-swipe-left" : "page-swipe-right";
    document.body.classList.add(dirClass);
    const target = pages[nextIdx];
    if (target === "__profile__") {
      const profileToggle = document.querySelector("[data-profile-toggle]");
      if (profileToggle) {
        profileToggle.click();
      }
      navigating = false;
      return;
    }
    const prefersReduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const delay = prefersReduce ? 0 : 220;
    setTimeout(() => {
      window.location.href = target;
    }, delay);
  }

  document.addEventListener("touchstart", onTouchStart, { passive: true });
  document.addEventListener("touchend", onTouchEnd, { passive: true });
})();
