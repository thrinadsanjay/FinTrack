(function () {
  var root = document.querySelector("[data-inbox-page]");
  if (!root) return;

  var listEl = document.querySelector("[data-inbox-list]");
  var metaEl = document.querySelector("[data-inbox-meta]");
  var reportEl = document.querySelector("[data-inbox-report]");
  var attention = document.querySelector("[data-inbox-attention]");
  var duplicatesOnly = document.querySelector("[data-inbox-duplicates]");
  var searchInput = document.querySelector("[data-inbox-search]");
  var sourceFilter = document.querySelector("[data-inbox-source]");
  var dialog = document.querySelector("[data-inbox-review-dialog]");
  var form = document.querySelector("[data-inbox-review-form]");

  var rowsCache = [];
  var categoryCache = {};

  function csrf() {
    return window.FinTrack && window.FinTrack.csrfToken ? window.FinTrack.csrfToken() : "";
  }

  function toast(message, type) {
    if (window.FinTrack && window.FinTrack.toast) window.FinTrack.toast(message, type || "success");
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function escapeAttr(value) {
    return escapeHtml(value).replace(/'/g, "&#39;");
  }

  function money(value) {
    if (window.FTFormat) return FTFormat.formatINRDigits(value);
    return Number(value || 0).toLocaleString("en-IN", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  function syncApproveButton() {
    var bulk = document.querySelector("[data-inbox-bulk]");
    if (!bulk) return;
    var pendingEl = document.querySelector("[data-kpi-pending]");
    var pending = Number((pendingEl && pendingEl.textContent) || 0);
    var empty = !rowsCache.length || pending <= 0;
    bulk.disabled = empty;
    bulk.classList.toggle("ft-btn--secondary", empty);
    bulk.classList.toggle("ft-btn--primary", !empty);
  }

  function setKpi(name, value) {
    var el = document.querySelector("[data-kpi-" + name + "]");
    if (el) el.textContent = value;
  }

  function sourceLabel(source) {
    if (source === "sms") return "SMS";
    if (source === "csv") return "CSV";
    return "Statement";
  }

  function clearSelect(select, placeholder) {
    if (!select) return;
    select.innerHTML = "";
    var opt = document.createElement("option");
    opt.value = "";
    opt.textContent = placeholder;
    select.appendChild(opt);
  }

  function fillSelect(select, items, placeholder) {
    clearSelect(select, placeholder);
    (items || []).forEach(function (item) {
      var code = item.code || item.id || item.value;
      var label = item.name || item.label || code;
      if (!code) return;
      var opt = document.createElement("option");
      opt.value = code;
      opt.textContent = label;
      select.appendChild(opt);
    });
  }

  async function loadCategories(txType, selectedCode) {
    var type = txType || "debit";
    if (!categoryCache[type]) {
      var res = await fetch("/api/categories?type=" + encodeURIComponent(type));
      var data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to load categories");
      categoryCache[type] = Array.isArray(data) ? data : data.categories || [];
    }
    var categorySelect = form.querySelector("[data-review-category]");
    fillSelect(categorySelect, categoryCache[type], "Select category");
    if (selectedCode) categorySelect.value = selectedCode;
    return categoryCache[type];
  }

  async function loadSubcategories(txType, categoryCode, selectedCode) {
    var subcategorySelect = form.querySelector("[data-review-subcategory]");
    if (!categoryCode) {
      clearSelect(subcategorySelect, "Select category first");
      return;
    }
    clearSelect(subcategorySelect, "Loading…");
    var res = await fetch(
      "/api/categories/" +
        encodeURIComponent(categoryCode) +
        "/subcategories?type=" +
        encodeURIComponent(txType || "debit")
    );
    var data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to load subcategories");
    var items = Array.isArray(data) ? data : data.subcategories || [];
    fillSelect(subcategorySelect, items, "Select subcategory");
    if (selectedCode) subcategorySelect.value = selectedCode;
  }

  function filteredRows() {
    var query = ((searchInput && searchInput.value) || "").trim().toLowerCase();
    var source = (sourceFilter && sourceFilter.value) || "";
    return rowsCache.filter(function (row) {
      if (source && String(row.source || "") !== source) return false;
      if (duplicatesOnly && duplicatesOnly.checked && !row.possible_duplicate) return false;
      if (!query) return true;
      var hay = [
        row.description,
        row.detected_merchant,
        row.account_name,
        row.amount,
        row.category,
        row.subcategory_name,
        row.raw_description,
      ]
        .join(" ")
        .toLowerCase();
      return hay.indexOf(query) !== -1;
    });
  }

  function renderRows() {
    var rows = filteredRows();
    if (!rows.length) {
      listEl.innerHTML =
        '<div class="inx-empty"><p class="inx-empty__title">Inbox is clear</p><p>Upload an HDFC or SBI PDF, or sync SMS, to catch missing rows such as “Swiggy → Food” before they hit the ledger.</p></div>';
      return;
    }

    listEl.innerHTML = "";
    rows.forEach(function (row) {
      var needs = row.needs_attention || [];
      var conf =
        row.confidence_percent != null
          ? row.confidence_percent
          : Math.round((row.confidence || 0) * 100);
      var typeKey = row.type === "credit" ? "credit" : "debit";
      var card = document.createElement("article");
      card.className =
        "inx-card is-" +
        typeKey +
        (needs.length ? " is-attention" : "");
      card.innerHTML =
        '<div class="inx-card__icon" aria-hidden="true"><i class="fa-solid ' +
        (typeKey === "credit" ? "fa-arrow-down" : "fa-arrow-up") +
        '"></i></div>' +
        '<div class="inx-card__main">' +
        '<div class="inx-card__title">' +
        escapeHtml(row.description || row.detected_merchant || "Inbox item") +
        "</div>" +
        '<div class="inx-card__meta">' +
        "<span>" +
        escapeHtml(row.account_name || "No account") +
        "</span>" +
        "<span>" +
        escapeHtml(row.date_key || "") +
        "</span>" +
        "<span>" +
        escapeHtml((row.mode || "unknown").toUpperCase()) +
        "</span>" +
        "</div>" +
        '<div class="inx-card__tags">' +
        '<span class="ft-badge">' +
        escapeHtml(sourceLabel(row.source)) +
        "</span>" +
        '<span class="ft-badge ' +
        (conf >= 85 ? "ft-badge--positive" : "ft-badge--warning") +
        '">' +
        conf +
        "%</span>" +
        (row.category
          ? '<span class="ft-badge">' +
            escapeHtml(row.category) +
            (row.subcategory_name ? " · " + escapeHtml(row.subcategory_name) : "") +
            "</span>"
          : '<span class="ft-badge ft-badge--warning">Category needed</span>') +
        (row.possible_duplicate || (needs.indexOf("possible_duplicate") !== -1)
          ? '<span class="ft-badge ft-badge--warning">Possible duplicate' +
            (row.duplicate_match && row.duplicate_match.confidence
              ? " · " + row.duplicate_match.confidence + "%"
              : "") +
            "</span>"
          : "") +
        (row.duplicate_match && row.duplicate_match.existing
          ? '<div class="inx-dup">Matches existing ₹ ' +
            money(row.duplicate_match.existing.amount) +
            " " +
            escapeHtml(row.duplicate_match.existing.description || "") +
            " on " +
            escapeHtml(row.duplicate_match.existing.date || "") +
            " — " +
            escapeHtml((row.duplicate_match.reasons || []).join(", ")) +
            "</div>"
          : "") +
        "</div></div>" +
        '<div class="inx-card__side">' +
        '<div class="inx-card__amount">' +
        (typeKey === "credit" ? "+" : "−") +
        "₹ " +
        money(row.amount) +
        "</div>" +
        '<div class="inx-card__actions">' +
        '<button type="button" class="ft-btn ft-btn--primary ft-btn--sm" data-review="' +
        escapeAttr(row.id) +
        '">Review</button>' +
        '<button type="button" class="ft-btn ft-btn--ghost ft-btn--sm" data-discard="' +
        escapeAttr(row.id) +
        '">' +
        (row.possible_duplicate ? "Skip import" : "Discard") +
        "</button>" +
        "</div></div>";
      listEl.appendChild(card);
    });
  }

  async function loadInbox() {
    listEl.innerHTML = '<div class="inx-empty">Loading inbox…</div>';
    var url =
      "/transaction-inbox/list" +
      (attention && attention.checked ? "?needs_attention=true" : "");
    try {
      var res = await fetch(url);
      var data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to load inbox");
      rowsCache = data.rows || data.items || [];
      var summary = data.summary || {};
      setKpi("pending", summary.pending_count != null ? summary.pending_count : rowsCache.length);
      setKpi(
        "attention",
        summary.needs_attention_count != null ? summary.needs_attention_count : 0
      );
      setKpi("sms", summary.sms_count != null ? summary.sms_count : 0);
      setKpi("pdf", summary.statement_count != null ? summary.statement_count : 0);
      setKpi("total", "₹ " + money(summary.inbox_total || 0));
      if (metaEl) {
        metaEl.textContent =
          (summary.pending_count != null ? summary.pending_count : rowsCache.length) +
          " pending · " +
          (summary.needs_attention_count != null ? summary.needs_attention_count : 0) +
          " need attention · review before posting";
      }
      renderRows();
      syncApproveButton();
    } catch (err) {
      listEl.innerHTML =
        '<div class="inx-empty">' + escapeHtml(err.message || "Failed") + "</div>";
    }
  }

  function findRow(id) {
    return rowsCache.find(function (row) {
      return String(row.id) === String(id);
    });
  }

  async function openReview(rowId) {
    var row = findRow(rowId);
    if (!row || !dialog || !form) return;
    form.querySelector("[data-review-id]").value = row.id;
    form.querySelector("[data-review-date]").value = row.date_key || "";
    form.querySelector("[data-review-amount]").value = row.amount || "";
    form.querySelector("[data-review-type]").value = row.type === "credit" ? "credit" : "debit";
    form.querySelector("[data-review-mode]").value = row.mode || "unknown";
    form.querySelector("[data-review-description]").value = row.description || "";
    var accountSelect = form.querySelector("[data-review-account]");
    if (accountSelect && row.account_id) accountSelect.value = row.account_id;
    var hint = form.querySelector("[data-review-hint]");
    if (hint) {
      hint.textContent = row.possible_duplicate
        ? "Possible duplicate — Keep both to post it, or Skip import to leave the existing ledger row untouched."
        : "Fill missing details, then approve into the ledger.";
    }
    var dup = form.querySelector("[data-review-duplicate]");
    if (dup) {
      if (row.duplicate_match && row.duplicate_match.existing) {
        dup.hidden = false;
        dup.innerHTML =
          "<strong>Possible duplicate (" +
          (row.duplicate_match.confidence || "") +
          "%)</strong><br>Existing: ₹ " +
          money(row.duplicate_match.existing.amount) +
          " · " +
          escapeHtml(row.duplicate_match.existing.description || "") +
          " · " +
          escapeHtml(row.duplicate_match.existing.date || "") +
          "<br>" +
          escapeHtml((row.duplicate_match.reasons || []).join(" · "));
      } else {
        dup.hidden = true;
        dup.innerHTML = "";
      }
    }
    var raw = form.querySelector("[data-review-raw]");
    if (raw) {
      if (row.raw_description && row.raw_description !== row.description) {
        raw.hidden = false;
        raw.textContent = "Original: " + row.raw_description;
      } else {
        raw.hidden = true;
        raw.textContent = "";
      }
    }
    await loadCategories(row.type, row.category_code || "");
    await loadSubcategories(row.type, row.category_code || "", row.subcategory_code || "");
    if (typeof dialog.showModal === "function") dialog.showModal();
  }

  function closeDialog() {
    if (dialog && typeof dialog.close === "function") dialog.close();
  }

  function reviewPayload() {
    return {
      csrf_token: csrf(),
      row_id: form.querySelector("[data-review-id]").value,
      date: form.querySelector("[data-review-date]").value,
      amount: parseFloat(form.querySelector("[data-review-amount]").value),
      type: form.querySelector("[data-review-type]").value,
      mode: form.querySelector("[data-review-mode]").value,
      description: form.querySelector("[data-review-description]").value,
      account_id: form.querySelector("[data-review-account]").value,
      category_code: form.querySelector("[data-review-category]").value,
      subcategory_code: form.querySelector("[data-review-subcategory]").value,
    };
  }

  async function saveReview(approveAfter) {
    var payload = reviewPayload();
    if (!payload.category_code || !payload.subcategory_code) {
      throw new Error("Category and subcategory are required");
    }
    var updateRes = await fetch("/transaction-inbox/update-row", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf(),
      },
      body: JSON.stringify(payload),
    });
    var updateData = await updateRes.json();
    if (!updateRes.ok) throw new Error(updateData.detail || "Save failed");

    if (!approveAfter) {
      toast("Saved", "success");
      closeDialog();
      await loadInbox();
      return;
    }

    var approveRes = await fetch("/transaction-inbox/approve", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf(),
      },
      body: JSON.stringify({ csrf_token: csrf(), row_ids: [payload.row_id] }),
    });
    var approveData = await approveRes.json();
    if (!approveRes.ok) throw new Error(approveData.detail || "Approve failed");
    if (approveData.failed && approveData.failed.length) {
      throw new Error(approveData.failed[0].error || "Approve failed");
    }
    toast("Approved into ledger", "success");
    closeDialog();
    await loadInbox();
  }

  listEl.addEventListener("click", async function (event) {
    var reviewBtn = event.target.closest("[data-review]");
    var discardBtn = event.target.closest("[data-discard]");
    if (reviewBtn) {
      try {
        await openReview(reviewBtn.getAttribute("data-review"));
      } catch (err) {
        toast(err.message || "Unable to open review", "error");
      }
      return;
    }
    if (discardBtn) {
      if (!confirm("Discard this candidate?")) return;
      try {
        var res = await fetch("/transaction-inbox/discard", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf(),
          },
          body: JSON.stringify({
            csrf_token: csrf(),
            row_ids: [discardBtn.getAttribute("data-discard")],
          }),
        });
        var data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Discard failed");
        toast("Discarded", "success");
        loadInbox();
      } catch (err) {
        toast(err.message || "Discard failed", "error");
      }
    }
  });

  if (form) {
    form.addEventListener("submit", async function (event) {
      event.preventDefault();
      try {
        await saveReview(true);
      } catch (err) {
        toast(err.message || "Approve failed", "error");
      }
    });

    var skipBtn = form.querySelector("[data-review-skip]");
    if (skipBtn) {
      skipBtn.addEventListener("click", async function () {
        var rowId = form.querySelector("[data-review-id]").value;
        try {
          var res = await fetch("/transaction-inbox/discard", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-CSRF-Token": csrf(),
            },
            body: JSON.stringify({ csrf_token: csrf(), row_ids: [rowId] }),
          });
          var data = await res.json();
          if (!res.ok) throw new Error(data.detail || "Skip failed");
          toast("Import skipped. Existing transaction kept.", "success");
          closeDialog();
          loadInbox();
        } catch (err) {
          toast(err.message || "Skip failed", "error");
        }
      });
    }

    var typeSelect = form.querySelector("[data-review-type]");
    var categorySelect = form.querySelector("[data-review-category]");
    if (typeSelect) {
      typeSelect.addEventListener("change", async function () {
        try {
          await loadCategories(typeSelect.value, "");
          await loadSubcategories(typeSelect.value, "", "");
        } catch (err) {
          toast(err.message || "Failed to load categories", "error");
        }
      });
    }
    if (categorySelect) {
      categorySelect.addEventListener("change", async function () {
        try {
          await loadSubcategories(
            typeSelect ? typeSelect.value : "debit",
            categorySelect.value,
            ""
          );
        } catch (err) {
          toast(err.message || "Failed to load subcategories", "error");
        }
      });
    }
  }

  if (dialog) {
    dialog.querySelectorAll("[data-dialog-close]").forEach(function (btn) {
      btn.addEventListener("click", closeDialog);
    });
    dialog.addEventListener("click", function (event) {
      if (event.target === dialog) closeDialog();
    });
  }

  var skipDup = document.querySelector("[data-inbox-skip-duplicates]");
  if (skipDup) {
    skipDup.addEventListener("click", async function () {
      if (!confirm("Skip all possible duplicates? Existing ledger transactions will not be deleted.")) return;
      try {
        var res = await fetch("/transaction-inbox/skip-duplicates", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf(),
          },
          body: JSON.stringify({ csrf_token: csrf() }),
        });
        var data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Skip failed");
        toast("Skipped " + (data.discarded_count || 0) + " duplicate import(s)", "success");
        loadInbox();
      } catch (err) {
        toast(err.message || "Skip failed", "error");
      }
    });
  }

  var bulk = document.querySelector("[data-inbox-bulk]");
  if (bulk) {
    bulk.addEventListener("click", async function () {
      try {
        var res = await fetch("/transaction-inbox/approve-high-confidence", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf(),
          },
          body: JSON.stringify({ csrf_token: csrf(), min_confidence: 85 }),
        });
        var data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Bulk approve failed");
        var approved = data.approved_count || 0;
        toast(
          approved
            ? approved + " high-confidence item(s) approved"
            : "No ready items to approve",
          approved ? "success" : "error"
        );
        loadInbox();
      } catch (err) {
        toast(err.message || "Bulk approve failed", "error");
      }
    });
  }

  var upload = document.querySelector("[data-inbox-upload]");
  if (upload) {
    upload.addEventListener("change", async function () {
      if (!upload.files || !upload.files[0]) return;
      var accountSelect = document.querySelector("#inbox_upload_account");
      if (!accountSelect || !accountSelect.value) {
        toast("Add an account before uploading", "error");
        return;
      }
      var body = new FormData();
      body.append("statement_file", upload.files[0]);
      body.append("account_id", accountSelect.value);
      body.append("csrf_token", csrf());
      try {
        var res = await fetch("/transaction-inbox/upload-statement", {
          method: "POST",
          headers: { "X-CSRF-Token": csrf() },
          body: body,
        });
        var data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Upload failed");
        if (reportEl) {
          reportEl.hidden = false;
          reportEl.textContent =
            (data.detail || "Upload complete") +
            (data.soft_duplicates
              ? " · " + data.soft_duplicates + " soft-matched"
              : "");
        }
        toast(data.detail || "Statement uploaded", "success");
        loadInbox();
      } catch (err) {
        toast(err.message || "Upload failed", "error");
      } finally {
        upload.value = "";
      }
    });
  }

  var syncSms = document.querySelector("[data-inbox-sync-sms]");
  if (syncSms) {
    syncSms.addEventListener("click", async function () {
      var accountSelect = document.querySelector("#inbox_upload_account");
      if (!accountSelect || !accountSelect.value) {
        toast("Select an account first", "error");
        return;
      }
      var body = new FormData();
      body.append("account_id", accountSelect.value);
      body.append("csrf_token", csrf());
      try {
        var res = await fetch("/transaction-inbox/sms/sync-buffer", {
          method: "POST",
          headers: { "X-CSRF-Token": csrf() },
          body: body,
        });
        var data = await res.json();
        if (!res.ok) throw new Error(data.detail || "SMS sync failed");
        toast(
          "SMS sync: added " +
            (data.inserted_count || 0) +
            ", skipped " +
            (data.duplicate_count || 0),
          "success"
        );
        loadInbox();
      } catch (err) {
        toast(err.message || "SMS sync failed", "error");
      }
    });
  }

  var clearPending = document.querySelector("[data-inbox-clear-pending]");
  if (clearPending) {
    clearPending.addEventListener("click", async function () {
      if (!confirm("Clear all pending inbox items?")) return;
      try {
        var res = await fetch("/transaction-inbox/buffer/clear", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf(),
          },
          body: JSON.stringify({ csrf_token: csrf() }),
        });
        var data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Clear failed");
        toast("Cleared " + (data.cleared_count || 0) + " items", "success");
        loadInbox();
      } catch (err) {
        toast(err.message || "Clear failed", "error");
      }
    });
  }

  if (attention) attention.addEventListener("change", loadInbox);
  if (duplicatesOnly) duplicatesOnly.addEventListener("change", renderRows);
  if (searchInput) searchInput.addEventListener("input", renderRows);
  if (sourceFilter) sourceFilter.addEventListener("change", renderRows);

  loadInbox();
})();
