(function () {
  function csrf() {
    return window.FinTrack ? window.FinTrack.csrfToken() : "";
  }

  var askRoot = document.querySelector("[data-ask-page]");
  if (askRoot) {
    var form = askRoot.querySelector("[data-ask-form]");
    var input = askRoot.querySelector("[data-ask-input]");
    var reply = askRoot.querySelector("[data-ask-reply]");
    var available = askRoot.getAttribute("data-ai-available") === "true";

    function ask(question) {
      if (!available) return;
      if (reply) {
        reply.hidden = false;
        reply.textContent = "Looking up your records…";
      }
      fetch("/api/ai/ask", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf() },
        body: JSON.stringify({ question: question }),
      })
        .then(function (res) {
          return res.json();
        })
        .then(function (data) {
          if (!reply) return;
          reply.hidden = false;
          reply.textContent = data.reply || "No answer.";
        })
        .catch(function () {
          if (reply) reply.textContent = "The assistant could not complete that request.";
        });
    }

    if (form) {
      form.addEventListener("submit", function (ev) {
        ev.preventDefault();
        var q = (input && input.value) || "";
        if (q.trim()) ask(q.trim());
      });
    }
    askRoot.querySelectorAll("[data-ask-example]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (input) input.value = btn.textContent.trim();
        ask(btn.textContent.trim());
      });
    });
    if (input && input.value.trim() && available) ask(input.value.trim());
  }

  document.querySelectorAll("[data-explain]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var article = btn.closest("[data-insight]");
      var out = article ? article.querySelector("[data-explain-out]") : null;
      if (out) {
        out.hidden = false;
        out.textContent = "Explaining from recorded facts…";
      }
      fetch("/api/ai/explain", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf() },
        body: JSON.stringify({
          key: btn.getAttribute("data-key") || "",
          title: btn.getAttribute("data-title") || "",
          detail: btn.getAttribute("data-detail") || "",
          category: btn.getAttribute("data-category") || "",
        }),
      })
        .then(function (res) {
          return res.json();
        })
        .then(function (data) {
          if (out) out.textContent = data.explanation || "";
        })
        .catch(function () {
          if (out) out.textContent = "Explanation is unavailable.";
        });
    });
  });
})();
