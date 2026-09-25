/* Mobile shell behaviour (all pages). Desktop is unaffected: every handler checks isMobile()
 * or only acts on mobile-only markup (sheets, avatar button, bottom nav). */
(function () {
  var mq = window.matchMedia ? window.matchMedia("(max-width: 899px)") : null;
  function isMobile() {
    return !!(mq && mq.matches);
  }
  function toast(message, tone) {
    if (window.FinTrack && window.FinTrack.toast) window.FinTrack.toast(message, tone);
  }

  /* ---------------- Bottom sheets (account menu, transaction filters) ---------------- */
  var openSheet = null;
  var sheetOpener = null;

  function focusables(root) {
    return Array.prototype.filter.call(
      root.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select, [tabindex]:not([tabindex="-1"])'),
      function (el) { return el.offsetParent !== null; }
    );
  }

  function showSheet(sheet, opener) {
    if (!sheet) return;
    if (openSheet && openSheet !== sheet) hideSheet(openSheet, false);
    sheetOpener = opener || document.activeElement;
    sheet.hidden = false;
    document.body.classList.add("ft-sheet-open");
    requestAnimationFrame(function () { sheet.classList.add("is-open"); });
    openSheet = sheet;
    var first = focusables(sheet)[0];
    if (first) first.focus({ preventScroll: true });
  }

  function hideSheet(sheet, restoreFocus) {
    if (!sheet) return;
    sheet.classList.remove("is-open");
    document.body.classList.remove("ft-sheet-open");
    var done = function () { sheet.hidden = true; };
    var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) done(); else setTimeout(done, 180);
    if (openSheet === sheet) openSheet = null;
    if (restoreFocus !== false && sheetOpener && sheetOpener.focus) sheetOpener.focus({ preventScroll: true });
  }

  document.addEventListener("click", function (event) {
    var accountBtn = event.target.closest("[data-account-sheet-open]");
    if (accountBtn) {
      event.preventDefault();
      showSheet(document.querySelector("[data-account-sheet]"), accountBtn);
      return;
    }
    var sheetBtn = event.target.closest("[data-sheet-open]");
    if (sheetBtn) {
      event.preventDefault();
      showSheet(document.querySelector(sheetBtn.getAttribute("data-sheet-open")), sheetBtn);
      return;
    }
    if (openSheet && event.target.closest("[data-sheet-close]")) {
      event.preventDefault();
      hideSheet(openSheet);
    }
  });

  document.addEventListener("keydown", function (event) {
    if (!openSheet) return;
    if (event.key === "Escape") {
      hideSheet(openSheet);
      return;
    }
    if (event.key === "Tab") {
      // Keep keyboard focus inside the open sheet.
      var items = focusables(openSheet);
      if (!items.length) return;
      var first = items[0];
      var last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  });

  if (mq && mq.addEventListener) {
    mq.addEventListener("change", function () {
      if (!isMobile() && openSheet) hideSheet(openSheet, false);
    });
  }

  /* ---------------- "+" in the bottom nav ---------------- */
  document.addEventListener("click", function (event) {
    var add = event.target.closest("[data-mobile-add]");
    if (!add) return;
    // Already on a page with the add drawer: open it in place (no reload).
    var opener = document.querySelector("[data-open-add]");
    if (opener && document.querySelector("[data-add-drawer]")) {
      event.preventDefault();
      opener.click();
    }
  });

  // Focus the big amount field as soon as the add sheet opens (brings up the numeric keypad).
  var drawer = document.querySelector("[data-add-drawer]");
  if (drawer && "MutationObserver" in window) {
    var focusAmount = function () {
      if (drawer.hidden || !isMobile()) return;
      var amount = drawer.querySelector("#amount");
      if (amount && !amount.value) setTimeout(function () { amount.focus(); }, 120);
    };
    new MutationObserver(focusAmount).observe(drawer, { attributes: true, attributeFilter: ["hidden"] });
    focusAmount();
  }

  /* ---------------- Tap a list row to open its details ---------------- */
  document.addEventListener("click", function (event) {
    if (!isMobile()) return;
    var row = event.target.closest("tr[data-tx-row], tr[data-holding-row]");
    if (!row || event.target.closest("a, button, summary, details, form, input, select, label")) return;
    var view = row.querySelector("[data-view-tx], [data-view-account]");
    if (view) view.click();
  });

  /* ---------------- Keyboard up → keep floating UI out of the way ---------------- */
  var TYPING = /^(text|search|email|number|tel|url|password|date|datetime-local|month|time)$/;
  document.addEventListener("focusin", function (event) {
    var el = event.target;
    if ((el.tagName === "INPUT" && TYPING.test(el.type)) || el.tagName === "TEXTAREA" || el.tagName === "SELECT") {
      document.body.classList.add("ft-typing");
    }
  });
  document.addEventListener("focusout", function () {
    setTimeout(function () {
      var el = document.activeElement;
      if (!el || !(el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT")) {
        document.body.classList.remove("ft-typing");
      }
    }, 60);
  });

  /* ---------------- Network state: never pretend something was saved ---------------- */
  var banner = document.querySelector("[data-offline-banner]");
  function syncOnline() {
    var offline = navigator.onLine === false;
    if (banner) banner.hidden = !offline;
    document.body.classList.toggle("is-offline", offline);
  }
  window.addEventListener("online", function () {
    syncOnline();
    toast("Back online", "success");
  });
  window.addEventListener("offline", syncOnline);
  syncOnline();

  document.addEventListener(
    "submit",
    function (event) {
      var form = event.target;
      var method = String(form.getAttribute("method") || "get").toLowerCase();
      if (method === "post" && navigator.onLine === false) {
        event.preventDefault();
        event.stopImmediatePropagation();
        toast("You're offline. Nothing was saved. Try again when you're back online.", "error");
      }
    },
    true
  );

  /* Logout: drop any cached assets (there is no cached financial data, but be thorough). */
  document.addEventListener("click", function (event) {
    var out = event.target.closest('a[href="/logout"]');
    if (!out || !navigator.serviceWorker || !navigator.serviceWorker.controller) return;
    navigator.serviceWorker.controller.postMessage("clear");
  });

  /* ---------------- Installable app (PWA) ---------------- */
  if ("serviceWorker" in navigator && window.isSecureContext) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () {});
    });
  }
})();
