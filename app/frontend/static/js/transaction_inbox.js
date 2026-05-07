document.addEventListener("DOMContentLoaded", () => {
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const uploadForm = document.getElementById("statement-upload-form");
  const uploadResult = document.getElementById("upload-result");
  const rowsBody = document.getElementById("inbox-rows");
  const needsAttentionOnly = document.getElementById("needs-attention-only");
  const selectAll = document.getElementById("select-all-rows");
  const approveSelectedBtn = document.getElementById("approve-selected");
  const discardSelectedBtn = document.getElementById("discard-selected");

  const summaryEls = {
    pending: document.querySelector("[data-summary-pending]"),
    attention: document.querySelector("[data-summary-attention]"),
    statement: document.querySelector("[data-summary-statement]"),
    sms: document.querySelector("[data-summary-sms]"),
  };

  const categoryCache = {
    debit: null,
    credit: null,
  };

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

  function formatDateInput(value) {
    if (!value) return "";
    return String(value).slice(0, 10);
  }

  async function apiJson(url, options = {}) {
    const response = await fetch(url, {
      credentials: "same-origin",
      ...options,
    });
    const contentType = String(response.headers.get("content-type") || "");
    const payload = contentType.includes("application/json")
      ? await response.json()
      : {};
    if (!response.ok) {
      throw new Error(payload.detail || "Request failed");
    }
    return payload;
  }

  async function ensureCategories(type) {
    if (categoryCache[type]) return categoryCache[type];
    const payload = await apiJson(`/api/categories?type=${encodeURIComponent(type)}`);
    categoryCache[type] = payload.categories || [];
    return categoryCache[type];
  }

  function selectedIds() {
    return Array.from(rowsBody.querySelectorAll('input[data-row-select]:checked'))
      .map((node) => node.value);
  }

  function setSummary(summary) {
    summaryEls.pending.textContent = String(summary.pending_count || 0);
    summaryEls.attention.textContent = String(summary.needs_attention_count || 0);
    summaryEls.statement.textContent = String(summary.statement_count || 0);
    summaryEls.sms.textContent = String(summary.sms_count || 0);
  }

  async function renderRows(rows) {
    if (!rows.length) {
      rowsBody.innerHTML = '<tr><td colspan="10" class="inbox-empty-cell">Inbox is clear.</td></tr>';
      return;
    }

    const debitCategories = await ensureCategories("debit");
    const creditCategories = await ensureCategories("credit");

    rowsBody.innerHTML = rows.map((row) => {
      const categories = row.type === "credit" ? creditCategories : debitCategories;
      const options = ['<option value="">Select category</option>']
        .concat(categories.map((cat) => (
          `<option value="${escapeHtml(cat.code)}" ${row.category_code === cat.code ? "selected" : ""}>${escapeHtml(cat.name)}</option>`
        )))
        .join("");

      return `
        <tr class="inbox-row ${row.needs_attention ? "inbox-row--attention" : ""}" data-row-id="${escapeHtml(row.id)}">
          <td><input type="checkbox" data-row-select value="${escapeHtml(row.id)}" aria-label="Select row"></td>
          <td><input type="date" data-field="date" value="${escapeHtml(formatDateInput(row.date))}"></td>
          <td><input type="text" data-field="description" value="${escapeHtml(row.description)}"></td>
          <td><input type="number" step="0.01" min="0.01" data-field="amount" value="${escapeHtml(fmtAmount(row.amount))}"></td>
          <td>
            <select data-field="type">
              <option value="debit" ${row.type === "debit" ? "selected" : ""}>Debit</option>
              <option value="credit" ${row.type === "credit" ? "selected" : ""}>Credit</option>
            </select>
          </td>
          <td>
            <select data-field="mode">
              ${["upi", "card", "neft", "imps", "online", "unknown"].map((mode) => (
                `<option value="${mode}" ${row.mode === mode ? "selected" : ""}>${mode.toUpperCase()}</option>`
              )).join("")}
            </select>
          </td>
          <td><select data-field="category_code">${options}</select></td>
          <td><span class="inbox-account-pill">${escapeHtml(row.account_name || "Account")}</span></td>
          <td>
            <span class="attention-badge ${row.needs_attention ? "is-active" : ""}">
              ${row.needs_attention ? "Needs attention" : "Ready"}
            </span>
          </td>
          <td class="inbox-actions-cell">
            <button type="button" class="chip chip-subtle" data-action="save">Save</button>
            <button type="button" class="chip chip-danger chip-danger--ghost" data-action="discard">Discard</button>
          </td>
        </tr>
      `;
    }).join("");
  }

  async function refreshCategoryOptions(rowEl) {
    const typeSelect = rowEl.querySelector('[data-field="type"]');
    const categorySelect = rowEl.querySelector('[data-field="category_code"]');
    if (!(typeSelect instanceof HTMLSelectElement) || !(categorySelect instanceof HTMLSelectElement)) {
      return;
    }
    const categories = await ensureCategories(typeSelect.value === "credit" ? "credit" : "debit");
    categorySelect.innerHTML = ['<option value="">Select category</option>']
      .concat(categories.map((cat) => `<option value="${escapeHtml(cat.code)}">${escapeHtml(cat.name)}</option>`))
      .join("");
  }

  async function loadRows() {
    rowsBody.innerHTML = '<tr><td colspan="10" class="inbox-empty-cell">Loading inbox...</td></tr>';
    selectAll.checked = false;
    const payload = await apiJson(`/transaction-inbox/list?needs_attention=${needsAttentionOnly.checked ? "true" : "false"}`);
    setSummary(payload.summary || {});
    await renderRows(payload.rows || []);
  }

  function rowPayload(rowEl) {
    return {
      row_id: rowEl.dataset.rowId,
      date: rowEl.querySelector('[data-field="date"]').value,
      description: rowEl.querySelector('[data-field="description"]').value,
      amount: Number(rowEl.querySelector('[data-field="amount"]').value),
      type: rowEl.querySelector('[data-field="type"]').value,
      mode: rowEl.querySelector('[data-field="mode"]').value,
      category_code: rowEl.querySelector('[data-field="category_code"]').value,
      csrf_token: csrfToken,
    };
  }

  async function saveRow(rowEl) {
    const payload = rowPayload(rowEl);
    await apiJson("/transaction-inbox/update-row", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (typeof window.ftNotify === "function") {
      window.ftNotify("Inbox row saved", "success");
    }
    await loadRows();
  }

  async function bulkAction(url, rowIds, successMessage) {
    if (!rowIds.length) {
      if (typeof window.ftNotify === "function") {
        window.ftNotify("Select at least one row", "error");
      }
      return;
    }

    const payload = await apiJson(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ row_ids: rowIds, csrf_token: csrfToken }),
    });

    if (payload.failed?.length) {
      const firstError = payload.failed[0]?.error || "Some rows could not be processed";
      if (typeof window.ftNotify === "function") {
        window.ftNotify(firstError, "error");
      }
    } else if (typeof window.ftNotify === "function") {
      window.ftNotify(successMessage, "success");
    }

    await loadRows();
  }

  uploadForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    uploadResult.textContent = "Importing...";
    const formData = new FormData(uploadForm);
    try {
      const payload = await apiJson("/transaction-inbox/upload-statement", {
        method: "POST",
        body: formData,
      });
      uploadResult.textContent = `${payload.inserted_count} imported, ${payload.duplicate_count} skipped, ${payload.needs_attention_count} need attention.`;
      await loadRows();
      uploadForm.reset();
    } catch (error) {
      uploadResult.textContent = error instanceof Error ? error.message : "Import failed";
    }
  });

  needsAttentionOnly?.addEventListener("change", () => {
    loadRows().catch((error) => {
      if (typeof window.ftNotify === "function") {
        window.ftNotify(error instanceof Error ? error.message : "Unable to load inbox", "error");
      }
    });
  });

  selectAll?.addEventListener("change", () => {
    rowsBody.querySelectorAll('input[data-row-select]').forEach((checkbox) => {
      checkbox.checked = selectAll.checked;
    });
  });

  rowsBody?.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const action = target.dataset.action;
    if (!action) return;
    const rowEl = target.closest("[data-row-id]");
    if (!(rowEl instanceof HTMLElement)) return;

    if (action === "save") {
      saveRow(rowEl).catch((error) => {
        if (typeof window.ftNotify === "function") {
          window.ftNotify(error instanceof Error ? error.message : "Save failed", "error");
        }
      });
      return;
    }

    if (action === "discard") {
      bulkAction("/transaction-inbox/discard", [rowEl.dataset.rowId], "Inbox row discarded").catch((error) => {
        if (typeof window.ftNotify === "function") {
          window.ftNotify(error instanceof Error ? error.message : "Discard failed", "error");
        }
      });
    }
  });

  rowsBody?.addEventListener("change", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLSelectElement)) return;
    if (target.dataset.field !== "type") return;
    const rowEl = target.closest("[data-row-id]");
    if (!(rowEl instanceof HTMLElement)) return;
    refreshCategoryOptions(rowEl).catch(() => {});
  });

  approveSelectedBtn?.addEventListener("click", () => {
    bulkAction("/transaction-inbox/approve", selectedIds(), "Selected rows approved").catch((error) => {
      if (typeof window.ftNotify === "function") {
        window.ftNotify(error instanceof Error ? error.message : "Approve failed", "error");
      }
    });
  });

  discardSelectedBtn?.addEventListener("click", () => {
    bulkAction("/transaction-inbox/discard", selectedIds(), "Selected rows discarded").catch((error) => {
      if (typeof window.ftNotify === "function") {
        window.ftNotify(error instanceof Error ? error.message : "Discard failed", "error");
      }
    });
  });

  loadRows().catch((error) => {
    rowsBody.innerHTML = `<tr><td colspan="10" class="inbox-empty-cell">${escapeHtml(error instanceof Error ? error.message : "Unable to load inbox")}</td></tr>`;
  });
});
