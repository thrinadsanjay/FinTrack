/* Inbox page: mark read / dismiss using the existing notification endpoints. */
(function () {
  var root = document.querySelector("[data-inbox-center]");
  if (!root) return;

  function csrf() {
    return window.FinTrack ? window.FinTrack.csrfToken() : "";
  }

  function post(url, payload) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf() },
      body: JSON.stringify(payload),
    }).then(function (res) {
      if (!res.ok) throw new Error("Couldn't update. Please retry.");
      return res.json();
    });
  }

  function refreshBadges() {
    var unread = root.querySelectorAll(".ibx-item.is-unread").length;
    document.querySelectorAll(".ft-mobile-nav__dot").forEach(function (dot) {
      if (unread > 0) dot.textContent = unread > 99 ? "99+" : String(unread);
      else dot.remove();
    });
    var all = root.querySelector("[data-ibx-read-all]");
    if (all) all.hidden = unread === 0;
    var empty = root.querySelector("[data-ibx-empty]");
    if (empty) empty.hidden = root.querySelectorAll(".ibx-item").length > 0;
  }

  function markRead(item) {
    item.classList.remove("is-unread");
    var sr = item.querySelector(".ibx-item__title .sr-only");
    if (sr) sr.remove();
    var btn = item.querySelector("[data-ibx-read]");
    if (btn) btn.remove();
  }

  function fail(err) {
    if (window.FinTrack) window.FinTrack.toast(err.message || "Couldn't update. Please retry.", "error");
  }

  root.addEventListener("click", function (event) {
    var readBtn = event.target.closest("[data-ibx-read]");
    var dismissBtn = event.target.closest("[data-ibx-dismiss]");
    var allBtn = event.target.closest("[data-ibx-read-all]");
    if (readBtn || dismissBtn) {
      var item = event.target.closest("[data-ibx-id]");
      var id = item.getAttribute("data-ibx-id");
      var btn = readBtn || dismissBtn;
      btn.disabled = true;
      var req = readBtn
        ? post("/notifications/read", { ids: [id] }).then(function () { markRead(item); })
        : post("/notifications/archive", { ids: [id] }).then(function () { item.remove(); });
      req.then(refreshBadges).catch(function (err) { btn.disabled = false; fail(err); });
      return;
    }
    if (allBtn) {
      allBtn.disabled = true;
      post("/notifications/read", { all: true })
        .then(function () {
          root.querySelectorAll(".ibx-item.is-unread").forEach(markRead);
          refreshBadges();
          if (window.FinTrack) window.FinTrack.toast("All marked as read", "success");
        })
        .catch(fail)
        .then(function () { allBtn.disabled = false; });
    }
  });
})();
