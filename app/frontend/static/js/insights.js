(function () {
  // "Summarize my month": optional AI narrative over the same monthly numbers.
  var btn = document.querySelector("[data-month-summary]");
  var out = document.querySelector("[data-month-summary-out]");
  if (!btn || !out) return;

  btn.addEventListener("click", function () {
    btn.disabled = true;
    out.hidden = false;
    out.classList.add("is-loading");
    out.textContent = "Writing a summary from your recorded numbers…";
    fetch("/api/ai/review", { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        out.textContent = (data && data.narrative) || "A summary isn't available right now. The numbers below are unaffected.";
      })
      .catch(function () {
        out.textContent = "A summary isn't available right now. The numbers below are unaffected.";
      })
      .then(function () {
        out.classList.remove("is-loading");
        btn.disabled = false;
      });
  });
})();
