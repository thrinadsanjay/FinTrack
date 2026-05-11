/**
 * Transaction Inbox JavaScript - Complete Redesign
 * 
 * FEATURES:
 * - Render flat list of rows from backend
 * - Group by date for display
 * - Edit inline fields (description, amount, category, type)
 * - Select and bulk approve/discard
 * - Show detailed error messages on import
 * - Clear buffer with confirmation
 * - Auto-approve high confidence rows
 */

document.addEventListener("DOMContentLoaded", () => {
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const uploadForm = document.getElementById("statement-upload-form");
  const uploadResult = document.getElementById("upload-result");
  const smsResult = document.getElementById("sms-result");
  const smsBufferSyncForm = document.getElementById("sms-buffer-sync-form");
  const smsPermissionBtn = document.getElementById("sms-request-permission");
  const smsSyncDeviceBtn = document.getElementById("sms-sync-device");
  const smsClearBufferBtn = document.getElementById("sms-clear-buffer");
  const rowsBody = document.getElementById("inbox-rows");
  const needsAttentionOnly = document.getElementById("needs-attention-only");
  const selectAll = document.getElementById("select-all-rows");
  const approveSelectedBtn = document.getElementById("approve-selected");
  const discardSelectedBtn = document.getElementById("discard-selected");
  const approveHighConfidenceBtn = document.getElementById("approve-high-confidence");
  const clearPendingBufferBtn = document.getElementById("clear-pending-buffer");

  const statementAccountSelect = document.getElementById("statement-account-id");
  const smsAccountSelect = document.getElementById("sms-account-id");

  const summaryEls = {
    pending: document.querySelector("[data-summary-pending]"),
    attention: document.querySelector("[data-summary-attention]"),
    statement: document.querySelector("[data-summary-statement]"),
    sms: document.querySelector("[data-summary-sms]"),
    statementTotal: document.querySelector("[data-summary-statement-total]"),
    inboxTotal: document.querySelector("[data-summary-inbox-total]"),
  };

  const categoryCache = {
    debit: null,
    credit: null,
  };
  const subcategoryCache = new Map();

  // =========================================================================
  // UTILITY FUNCTIONS
  // =========================================================================

  function notify(message, level = "success") {
    if (typeof window.ftNotify === "function") {
      window.ftNotify(message, level);
      return;
    }
    console.log(`[${level.toUpperCase()}] ${message}`);
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function fmtAmount(value) {
    const amount = Number(value || 0);
    return Number.isFinite(amount) ? amount.toFixed(2) : "0.00";
  }

  function moneyLabel(value) {
    return `₹ ${fmtAmount(value)}`;
  }

  function formatDateInput(value) {
    if (!value) return "";
    return String(value).slice(0, 10);
  }

  function confidenceLabel(value) {
    const score = Number(value || 0);
    if (score >= 80) return "High";
    if (score >= 50) return "Medium";
    return "Low";
  }

  function confidenceClass(value) {
    const score = Number(value || 0);
    if (score >= 80) return "confidence-high";
    if (score >= 50) return "confidence-medium";
    return "confidence-low";
  }

  async function apiJson(url, options = {}) {
    const response = await fetch(url, {
      credentials: "same-origin",
      ...options,
    });
    const contentType = String(response.headers.get("content-type") || "");
    const payload = contentType.includes("application/json") ? await response.json() : {};
    if (!response.ok) {
      throw new Error(payload.detail || `Request failed with status ${response.status}`);
    }
    return payload;
  }

  async function ensureCategories(type) {
    if (categoryCache[type]) return categoryCache[type];
    const payload = await apiJson(`/api/categories?type=${encodeURIComponent(type)}`);
    categoryCache[type] = payload.categories || [];
    return categoryCache[type];
  }

  async function ensureSubcategories(type, categoryCode) {
    if (!type || !categoryCode) return [];
    const key = `${type}::${categoryCode}`;
    if (subcategoryCache.has(key)) return subcategoryCache.get(key);
    const payload = await apiJson(`/api/categories/${encodeURIComponent(categoryCode)}/subcategories?type=${encodeURIComponent(type)}`);
    const subcategories = payload.subcategories || [];
    subcategoryCache.set(key, subcategories);
    return subcategories;
  }

  function selectedIds() {
    return Array.from(rowsBody.querySelectorAll('input[data-row-select]:checked')).map((node) => node.value);
  }

  function setSummary(summary) {
    summaryEls.pending.textContent = String(summary.pending_count || 0);
    summaryEls.attention.textContent = String(summary.needs_attention_count || 0);
    summaryEls.statement.textContent = String(summary.statement_count || 0);
    summaryEls.sms.textContent = String(summary.sms_count || 0);
    summaryEls.statementTotal.textContent = moneyLabel(summary.statement_total || 0);
    summaryEls.inboxTotal.textContent = moneyLabel(summary.inbox_total || 0);
  }

  // =========================================================================
  // ROW RENDERING
  // =========================================================================

  function groupRowsByDate(rows) {
    const groups = new Map();
    rows.forEach((row) => {
      const key = (row.date || row.date_key || "Unknown").slice(0, 10) || "Unknown";
      if (!groups.has(key)) {
        groups.set(key, []);
      }
      groups.get(key).push(row);
    });

    return Array.from(groups.entries())
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([dateKey, groupedRows]) => ({
        date: dateKey,
        rows: groupedRows,
        total: groupedRows.reduce((sum, row) => sum + Number(row.amount || 0), 0),
      }));
  }

  function categoryOptionsMarkup(categories, selectedCode) {
    return ['<option value="">Select category</option>']
      .concat(
        categories.map((cat) => (
          `<option value="${escapeHtml(cat.code)}" ${selectedCode === cat.code ? "selected" : ""}>${escapeHtml(cat.name)}</option>`
        ))
      )
      .join("");
  }

  function subcategoryOptionsMarkup(subcategories, selectedCode) {
    return ['<option value="">Select subcategory</option>']
      .concat(
        subcategories.map((sub) => (
          `<option value="${escapeHtml(sub.code)}" ${selectedCode === sub.code ? "selected" : ""}>${escapeHtml(sub.name)}</option>`
        ))
      )
      .join("");
  }

  async function renderRows(payload) {
    // Get rows from payload (new format returns flat list)
    const rows = Array.isArray(payload.rows) ? payload.rows : [];
    
    if (!rows.length) {
      rowsBody.innerHTML = '<tr><td colspan="11" class="inbox-empty-cell">Inbox is empty. Import a statement to get started!</td></tr>';
      return;
    }

    // Group by date for display
    const groups = groupRowsByDate(rows);

    // Prefetch subcategories for category/type pairs present on rows.
    const pairMap = new Map();
    rows.forEach((row) => {
      if (row.type && row.category_code) {
        const key = `${row.type}::${row.category_code}`;
        pairMap.set(key, { type: row.type, categoryCode: row.category_code });
      }
    });
    await Promise.all(
      Array.from(pairMap.values()).map(({ type, categoryCode }) => ensureSubcategories(type, categoryCode).catch(() => []))
    );

    // Load categories
    let debitCategories = [];
    let creditCategories = [];
    try {
      [debitCategories, creditCategories] = await Promise.all([
        ensureCategories("debit"),
        ensureCategories("credit"),
      ]);
    } catch (error) {
      console.warn("Category lookup failed", error);
    }

    const html = [];
    
    groups.forEach((group) => {
      // Group header row
      html.push(`
        <tr class="inbox-group-row">
          <td colspan="11">
            <div class="inbox-group-meta">
              <strong>${escapeHtml(group.date)}</strong>
              <span>•</span>
              <span>${group.rows.length} row${group.rows.length !== 1 ? 's' : ''}</span>
              <span>•</span>
              <span>Total ${moneyLabel(group.total || 0)}</span>
            </div>
          </td>
        </tr>
      `);

      // Individual rows
      group.rows.forEach((row) => {
        const categories = row.type === "credit" ? creditCategories : debitCategories;
        const attentionClass = row.needs_attention ? "inbox-row--attention" : "";
        const attentionMark = row.needs_attention ? "⚠️" : "✓";
        
        html.push(`
          <tr class="inbox-row ${attentionClass}" data-row-id="${escapeHtml(row.id)}">
            <td><input type="checkbox" data-row-select value="${escapeHtml(row.id)}" aria-label="Select row"></td>
            <td><input type="date" data-field="date" value="${escapeHtml(formatDateInput(row.date))}" class="field-input" style="width: 100%;"></td>
            <td><input type="text" data-field="description" value="${escapeHtml(row.description)}" class="field-input" style="width: 100%;"></td>
            <td><input type="number" step="0.01" min="0.01" data-field="amount" value="${escapeHtml(fmtAmount(row.amount))}" class="field-input" style="width: 100%;"></td>
            <td>
              <select data-field="type" class="field-input" style="width: 100%;">
                <option value="debit" ${row.type === "debit" ? "selected" : ""}>Debit</option>
                <option value="credit" ${row.type === "credit" ? "selected" : ""}>Credit</option>
              </select>
            </td>
            <td>
              <select data-field="mode" class="field-input" style="width: 100%;">
                ${["upi", "card", "transfer", "unknown"].map((mode) => (
                  `<option value="${mode}" ${row.mode === mode ? "selected" : ""}>${mode.toUpperCase()}</option>`
                )).join("")}
              </select>
            </td>
            <td><select data-field="category_code" class="field-input" style="width: 100%;">${categoryOptionsMarkup(categories.length ? categories : [], row.category_code)}</select></td>
            <td>
              <select data-field="subcategory_code" class="field-input" style="width: 100%;">
                ${subcategoryOptionsMarkup(subcategoryCache.get(`${row.type}::${row.category_code}`) || [], row.subcategory_code)}
              </select>
            </td>
            <td>
              <span class="confidence-pill ${confidenceClass(row.confidence || 0)}" title="${Number(row.confidence || 0)}% confidence">
                ${Number(row.confidence || 0)}%
              </span>
            </td>
            <td title="Needs Attention">${attentionMark}</td>
            <td>
              <button type="button" class="row-save-btn" data-row-id="${escapeHtml(row.id)}" title="Save changes">💾</button>
            </td>
          </tr>
        `);
      });
    });

    rowsBody.innerHTML = html.join("");

    // Attach save handlers
    rowsBody.querySelectorAll(".row-save-btn").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.preventDefault();
        const rowId = btn.dataset.rowId;
        const rowEl = rowsBody.querySelector(`tr[data-row-id="${rowId}"]`);
        if (!rowEl) return;

        const fields = {};
        rowEl.querySelectorAll("[data-field]").forEach((input) => {
          fields[input.dataset.field] = input.value;
        });

        try {
          await apiJson("/transaction-inbox/update-row", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              csrf_token: csrfToken,
              row_id: rowId,
              ...fields,
            }),
          });
          notify("Row saved successfully");
          await loadInboxRows();
        } catch (error) {
          notify(`Failed to save row: ${error.message}`, "error");
        }
      });
    });

    // Keep subcategory list in sync with row category/type changes.
    rowsBody.querySelectorAll("tr[data-row-id]").forEach((rowEl) => {
      const categoryEl = rowEl.querySelector('[data-field="category_code"]');
      const typeEl = rowEl.querySelector('[data-field="type"]');
      const subcategoryEl = rowEl.querySelector('[data-field="subcategory_code"]');
      if (!categoryEl || !typeEl || !subcategoryEl) return;

      const reloadSubcategories = async () => {
        const selectedSub = subcategoryEl.value;
        const categoryCode = categoryEl.value;
        const txType = typeEl.value;
        subcategoryEl.innerHTML = '<option value="">Select subcategory</option>';

        if (!categoryCode || !txType) return;

        try {
          const subcategories = await ensureSubcategories(txType, categoryCode);
          subcategories.forEach((sub) => {
            const opt = document.createElement("option");
            opt.value = sub.code;
            opt.textContent = sub.name;
            if (selectedSub && selectedSub === sub.code) opt.selected = true;
            subcategoryEl.appendChild(opt);
          });
        } catch (error) {
          console.warn("Failed to load subcategories", error);
        }
      };

      categoryEl.addEventListener("change", reloadSubcategories);
      typeEl.addEventListener("change", reloadSubcategories);
    });
  }

  // =========================================================================
  // LOAD AND FILTER
  // =========================================================================

  async function loadInboxRows() {
    try {
      const payload = await apiJson(`/transaction-inbox/list?needs_attention=${needsAttentionOnly.checked}`);
      setSummary(payload.summary || {});
      await renderRows(payload);
    } catch (error) {
      notify(`Failed to load inbox: ${error.message}`, "error");
      rowsBody.innerHTML = `<tr><td colspan="11" class="inbox-empty-cell">Error loading inbox</td></tr>`;
    }
  }

  // Initial load
  loadInboxRows();

  // Filter handler
  needsAttentionOnly.addEventListener("change", loadInboxRows);

  // =========================================================================
  // SELECT ALL / DESELECT
  // =========================================================================

  selectAll.addEventListener("change", () => {
    rowsBody.querySelectorAll('input[data-row-select]').forEach((cb) => {
      cb.checked = selectAll.checked;
    });
  });

  // =========================================================================
  // STATEMENT UPLOAD
  // =========================================================================

  uploadForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    uploadResult.textContent = "";
    uploadResult.className = "inbox-upload-result result-info";
    uploadResult.textContent = "📤 Uploading and processing statement...";

    const formData = new FormData(uploadForm);

    try {
      const response = await fetch("/transaction-inbox/upload-statement", {
        method: "POST",
        credentials: "same-origin",
        body: formData,
      });

      const data = await response.json();

      if (!response.ok) {
        uploadResult.className = "inbox-upload-result result-error";
        uploadResult.innerHTML = `
          <div>❌ Upload failed: ${escapeHtml(data.detail || "Unknown error")}</div>
          ${data.stage1_errors?.length > 0 ? `<div class="error-detail"><strong>Parse errors:</strong> ${escapeHtml(data.stage1_errors.slice(0, 1).map(e => e.error).join("; "))}</div>` : ""}
          ${data.stage2_errors?.length > 0 ? `<div class="error-detail"><strong>Normalize errors:</strong> ${data.stage2_errors.length} rows failed</div>` : ""}
        `;
        return;
      }

      // Success
      uploadResult.className = "inbox-upload-result result-success";
      const sampleRows = Array.isArray(data.sample) ? data.sample : [];
      const sampleMarkup = sampleRows.length
        ? `
          <div style="margin-top: 8px; border-top: 1px dashed rgba(0,0,0,0.15); padding-top: 6px;">
            <div><strong>Sample Parsed Rows</strong></div>
            ${sampleRows.slice(0, 3).map((row) => `
              <div style="font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                ${escapeHtml(row.date)} | ${escapeHtml(String(row.amount))} | ${escapeHtml(row.type)} | ${escapeHtml(row.description || "")}
              </div>
            `).join("")}
          </div>
        `
        : "";
      uploadResult.innerHTML = `
        <div><strong>✓ Statement imported successfully!</strong></div>
        <div style="margin-top: 8px; font-size: 0.9em; line-height: 1.6;">
          <div>📥 Parsed: <strong>${data.parsed}</strong> rows from file</div>
          <div>✓ Normalized: <strong>${data.normalized}</strong> valid transactions</div>
          <div>📦 Added to Inbox: <strong>${data.inserted}</strong> new rows</div>
          <div>🔄 Duplicates: <strong>${data.duplicates}</strong> (already exist)</div>
          <div>⚠️ Need Review: <strong>${data.needs_attention}</strong> rows missing category</div>
          <div style="margin-top: 5px; border-top: 1px solid rgba(0,0,0,0.1); padding-top: 5px;">
            <span>Statement Total: <strong>${moneyLabel(data.statement_total)}</strong></span>
            <span style="margin-left: 15px;">Inbox Total: <strong>${moneyLabel(data.inbox_total)}</strong></span>
          </div>
          ${sampleMarkup}
        </div>
      `;

      uploadForm.reset();
      await loadInboxRows();
      notify(`✓ Imported ${data.inserted} transactions to inbox`);
    } catch (error) {
      uploadResult.className = "inbox-upload-result result-error";
      uploadResult.textContent = `❌ Error: ${error.message}`;
      notify(`Import failed: ${error.message}`, "error");
    }
  });

  // =========================================================================
  // BULK ACTIONS
  // =========================================================================

  approveSelectedBtn.addEventListener("click", async () => {
    const ids = selectedIds();
    if (!ids.length) {
      notify("Select at least one row to approve", "error");
      return;
    }

    try {
      const result = await apiJson("/transaction-inbox/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ csrf_token: csrfToken, row_ids: ids }),
      });

      notify(`✓ Approved ${result.approved_count} transactions`, "success");
      if (result.failed?.length) {
        notify(`⚠️ Failed to approve ${result.failed.length} rows: ${result.failed[0]?.error}`, "error");
      }
      await loadInboxRows();
    } catch (error) {
      notify(`Approve failed: ${error.message}`, "error");
    }
  });

  discardSelectedBtn.addEventListener("click", async () => {
    const ids = selectedIds();
    if (!ids.length) {
      notify("Select at least one row to discard", "error");
      return;
    }

    if (!confirm(`Discard ${ids.length} row(s)? They will be removed from the inbox.`)) {
      return;
    }

    try {
      const result = await apiJson("/transaction-inbox/discard", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ csrf_token: csrfToken, row_ids: ids }),
      });

      notify(`✓ Discarded ${result.discarded_count} transactions`, "success");
      await loadInboxRows();
    } catch (error) {
      notify(`Discard failed: ${error.message}`, "error");
    }
  });

  approveHighConfidenceBtn.addEventListener("click", async () => {
    try {
      const result = await apiJson("/transaction-inbox/approve-high-confidence", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ csrf_token: csrfToken, min_confidence: 70 }),
      });

      notify(`✓ Auto-approved ${result.approved_count} high-confidence transactions`, "success");
      if (result.failed?.length) {
        notify(`⚠️ Failed to approve ${result.failed.length} rows`, "error");
      }
      await loadInboxRows();
    } catch (error) {
      notify(`Auto-approve failed: ${error.message}`, "error");
    }
  });

  clearPendingBufferBtn.addEventListener("click", async () => {
    if (!confirm("❗ This will delete all pending and discarded transactions from your inbox buffer. This action cannot be undone. Continue?")) {
      return;
    }

    try {
      const result = await apiJson("/transaction-inbox/buffer/clear", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ csrf_token: csrfToken }),
      });

      notify(`✓ Cleared ${result.cleared_count} transactions from buffer`, "success");
      await loadInboxRows();
    } catch (error) {
      notify(`Clear buffer failed: ${error.message}`, "error");
    }
  });

  // =========================================================================
  // SMS HANDLERS
  // =========================================================================

  smsPermissionBtn.addEventListener("click", () => {
    notify("SMS READ permission request would go to Android bridge", "info");
  });

  smsSyncDeviceBtn.addEventListener("click", () => {
    notify("Device SMS sync would happen here when Android bridge is available", "info");
  });

  smsClearBufferBtn.addEventListener("click", async () => {
    if (!confirm("Clear all SMS from buffer?")) {
      return;
    }

    try {
      const result = await apiJson("/transaction-inbox/sms/clear-buffer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ csrf_token: csrfToken }),
      });

      notify(`✓ Cleared ${result.cleared_count} SMS from buffer`, "success");
    } catch (error) {
      notify(`Failed to clear SMS buffer: ${error.message}`, "error");
    }
  });

  smsBufferSyncForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    smsResult.textContent = "💬 Syncing SMS buffer...";
    smsResult.className = "inbox-upload-result result-info";

    try {
      const formData = new FormData(smsBufferSyncForm);
      const response = await fetch("/transaction-inbox/sms/sync-buffer", {
        method: "POST",
        credentials: "same-origin",
        body: formData,
      });

      const data = await response.json();

      if (!response.ok) {
        smsResult.className = "inbox-upload-result result-error";
        smsResult.textContent = `❌ Sync failed: ${data.detail || "Unknown error"}`;
        return;
      }

      smsResult.className = "inbox-upload-result result-success";
      smsResult.innerHTML = `
        <div><strong>✓ SMS buffer synced!</strong></div>
        <div style="margin-top: 8px; font-size: 0.9em;">
          <div>Inserted: <strong>${data.inserted_count}</strong> SMS</div>
          <div>Duplicates: <strong>${data.duplicate_count}</strong></div>
          <div>Needs Review: <strong>${data.needs_attention_count}</strong></div>
        </div>
      `;

      await loadInboxRows();
      notify(`✓ Synced ${data.inserted_count} SMS to inbox`, "success");
    } catch (error) {
      smsResult.className = "inbox-upload-result result-error";
      smsResult.textContent = `❌ Error: ${error.message}`;
      notify(`SMS sync failed: ${error.message}`, "error");
    }
  });
});
