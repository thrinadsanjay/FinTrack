(function () {
  var overlay = document.querySelector("[data-search-overlay]");
  var openBtns = document.querySelectorAll("[data-search-open]");
  var input = document.querySelector("[data-search-input]");
  var results = document.querySelector("[data-search-results]");
  var form = document.querySelector("[data-search-form]");
  if (!overlay || !input) return;

  var timer = null;

  function openSearch() {
    overlay.hidden = false;
    input.focus();
    input.select();
  }

  function closeSearch() {
    overlay.hidden = true;
  }

  function render(payload) {
    if (!results) return;
    var groups = (payload && payload.groups) || [];
    if (!groups.length) {
      results.innerHTML = '<div class="ft-search__empty">No matching records.</div>';
      return;
    }
    results.innerHTML = groups
      .map(function (group) {
        var items = (group.items || [])
          .map(function (item) {
            return (
              '<a class="ft-search__item" href="' +
              (item.href || "#") +
              '"><strong>' +
              escapeHtml(item.title || "") +
              "</strong><span>" +
              escapeHtml(item.subtitle || "") +
              "</span></a>"
            );
          })
          .join("");
        return (
          '<div class="ft-search__group"><div class="ft-search__group-title">' +
          escapeHtml(group.label || "") +
          "</div>" +
          items +
          "</div>"
        );
      })
      .join("");
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function query() {
    var q = (input.value || "").trim();
    if (q.length < 2) {
      results.innerHTML = "";
      return;
    }
    fetch("/api/search?q=" + encodeURIComponent(q), { credentials: "same-origin" })
      .then(function (res) {
        return res.json();
      })
      .then(render)
      .catch(function () {
        results.innerHTML = '<div class="ft-search__empty">Search is unavailable.</div>';
      });
  }

  openBtns.forEach(function (btn) {
    btn.addEventListener("click", openSearch);
  });
  overlay.addEventListener("click", function (ev) {
    if (ev.target === overlay) closeSearch();
  });
  if (form) {
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      query();
    });
  }
  input.addEventListener("input", function () {
    clearTimeout(timer);
    timer = setTimeout(query, 180);
  });
  document.addEventListener("keydown", function (ev) {
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "k") {
      ev.preventDefault();
      if (overlay.hidden) openSearch();
      else closeSearch();
    }
    if (ev.key === "Escape" && !overlay.hidden) closeSearch();
  });
})();
