(function () {
  var root = document.querySelector("[data-automations-page]");
  if (!root) return;

  function csrf() {
    return window.FinTrack ? window.FinTrack.csrfToken() : "";
  }

  function headers() {
    return { "Content-Type": "application/json", "X-CSRF-Token": csrf() };
  }

  var dialog = root.querySelector("[data-rule-dialog]");
  var form = root.querySelector("[data-rule-form]");

  function cond() {
    return [
      {
        type: root.querySelector("[data-rule-cond-type]").value,
        value: root.querySelector("[data-rule-cond-value]").value,
      },
    ];
  }

  function acts() {
    var type = root.querySelector("[data-rule-act-type]").value;
    var value = root.querySelector("[data-rule-act-value]").value.trim();
    var action = { type: type, message: value, title: root.querySelector("[data-rule-name]").value };
    if (type === "set_category" || type === "set_subcategory") {
      action.code = value.toLowerCase().replace(/\s+/g, "_");
      action.name = value;
    }
    return [action];
  }

  root.querySelector("[data-rule-new]").addEventListener("click", function () {
    root.querySelector("[data-rule-id-field]").value = "";
    root.querySelector("[data-rule-dialog-title]").textContent = "Create rule";
    form.reset();
    if (dialog.showModal) dialog.showModal();
  });

  root.querySelector("[data-rule-cancel]").addEventListener("click", function () {
    dialog.close();
  });

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var id = root.querySelector("[data-rule-id-field]").value;
    var payload = {
      name: root.querySelector("[data-rule-name]").value,
      enabled: true,
      priority: Number(root.querySelector("[data-rule-priority]").value || 0),
      conditions: cond(),
      actions: acts(),
    };
    var url = id ? "/api/rules/" + id : "/api/rules";
    fetch(url, {
      method: id ? "PATCH" : "POST",
      credentials: "same-origin",
      headers: headers(),
      body: JSON.stringify(payload),
    }).then(function (res) {
      if (!res.ok) return res.json().then(function (err) { throw err; });
      window.location.reload();
    }).catch(function (err) {
      window.alert((err && err.detail) || "Could not save the rule.");
    });
  });

  root.querySelectorAll("[data-rule-toggle]").forEach(function (box) {
    box.addEventListener("change", function () {
      var id = box.closest("[data-rule-id]").getAttribute("data-rule-id");
      fetch("/api/rules/" + id + "/toggle", {
        method: "POST",
        credentials: "same-origin",
        headers: headers(),
        body: JSON.stringify({ enabled: box.checked }),
      }).then(function () {
        window.location.reload();
      });
    });
  });

  root.querySelectorAll("[data-rule-delete]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      if (!window.confirm("Delete this rule?")) return;
      var id = btn.closest("[data-rule-id]").getAttribute("data-rule-id");
      fetch("/api/rules/" + id, {
        method: "DELETE",
        credentials: "same-origin",
        headers: headers(),
      }).then(function () {
        window.location.reload();
      });
    });
  });

  root.querySelectorAll("[data-rule-edit]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var card = btn.closest("[data-rule-id]");
      root.querySelector("[data-rule-id-field]").value = card.getAttribute("data-rule-id");
      root.querySelector("[data-rule-name]").value = card.querySelector("h2").textContent.trim();
      root.querySelector("[data-rule-dialog-title]").textContent = "Edit rule";
      if (dialog.showModal) dialog.showModal();
    });
  });

  root.querySelectorAll("[data-rule-history]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var id = btn.closest("[data-rule-id]").getAttribute("data-rule-id");
      fetch("/api/rules/runs?rule_id=" + encodeURIComponent(id), { credentials: "same-origin" })
        .then(function (res) { return res.json(); })
        .then(function (data) {
          var lines = (data.runs || []).map(function (run) {
            return (run.created_at || "") + " · " + (run.status || "") + " · " + (run.event_type || "");
          });
          window.alert(lines.length ? lines.join("\n") : "No runs yet.");
        });
    });
  });
})();
