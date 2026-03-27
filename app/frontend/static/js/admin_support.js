(() => {
  const root = document.querySelector("[data-support-root]");
  if (!root) return;

  const userListEl = root.querySelector("[data-support-user-list]");
  const messagesEl = root.querySelector("[data-support-messages]");
  const titleEl = root.querySelector("[data-support-user-title]");
  const subtitleEl = root.querySelector("[data-support-user-subtitle]");
  const refreshBtn = document.querySelector("[data-support-refresh]");
  const endBtn = document.querySelector("[data-support-end]");
  const composeForm = root.querySelector("[data-support-compose-form]");
  const composeInput = root.querySelector("[data-support-compose-input]");
  const composeSendBtn = root.querySelector("[data-support-compose-send]");

  let threads = [];
  let selectedUserId = null;
  let pollingTimer = null;
  let sendingReply = false;
  let selectedSessionStatus = "none";

  async function inlineNotice(btn, message, kind = "success", duration = 2200) {
    if (window.ftInlineFeedback?.showFor && btn) {
      await window.ftInlineFeedback.showFor(btn, message, kind, duration);
    }
  }

  function isExternalUserId(userId) {
    return String(userId || "").startsWith("guest:");
  }

  function formatDisplayName(name, userId) {
    const base = String(name || "Unknown User");
    return isExternalUserId(userId) ? `${base} (External)` : base;
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatTs(ts) {
    if (!ts) return "-";
    const parsed = new Date(ts);
    if (Number.isNaN(parsed.getTime())) return "-";
    return parsed.toLocaleString();
  }

  function renderThreadList() {
    if (!threads.length) {
      userListEl.innerHTML = '<p class="support-empty">No support requests yet.</p>';
      return;
    }

    userListEl.innerHTML = threads.map((thread) => {
      const pending = thread.pending_count > 0
        ? `<span class="support-badge">${thread.pending_count} new</span>`
        : "";
      return `
        <button type="button" class="support-user-btn ${selectedUserId === thread.user_id ? "active" : ""}" data-user-id="${thread.user_id}">
          <strong>${escapeHtml(formatDisplayName(thread.full_name || thread.username, thread.user_id))}</strong>
          <small>${escapeHtml(thread.email || "")}</small>
          <div class="support-user-meta">
            <small>${escapeHtml(formatTs(thread.last_timestamp))}</small>
            ${pending}
          </div>
        </button>
      `;
    }).join("");

    userListEl.querySelectorAll("[data-user-id]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const nextUserId = btn.getAttribute("data-user-id");
        if (!nextUserId || nextUserId === selectedUserId) return;
        selectedUserId = nextUserId;
        renderThreadList();
        loadMessages(nextUserId);
      });
    });
  }

  function renderMessages(payload) {
    const user = payload.user || {};
    const displayName = formatDisplayName(user.full_name || user.username, user.user_id);
    titleEl.textContent = displayName;
    subtitleEl.textContent = user.email || (isExternalUserId(user.user_id) ? "Guest user" : (user.user_id || ""));

    const externalSenderLabel = formatDisplayName(user.full_name || user.username, user.user_id);
    selectedSessionStatus = (payload.session || {}).status || "none";
    const canInteract = selectedSessionStatus === "active" || selectedSessionStatus === "pending_admin";
    setComposerEnabled(Boolean(selectedUserId && canInteract));
    if (endBtn) {
      endBtn.disabled = !(selectedUserId && canInteract);
    }

    const messages = payload.messages || [];
    if (!messages.length) {
      messagesEl.innerHTML = '<p class="support-empty">No support messages for this user.</p>';
      return;
    }

    messagesEl.innerHTML = messages.map((message) => `
      <div class="support-message ${escapeHtml(message.sender)}">
        <strong>${escapeHtml(message.sender === "user" ? externalSenderLabel : message.sender)} · ${escapeHtml(formatTs(message.timestamp))}</strong>
        <div>${escapeHtml(message.message)}</div>
      </div>
    `).join("");
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function setComposerEnabled(enabled) {
    if (!composeInput || !composeSendBtn) return;
    composeInput.disabled = !enabled || sendingReply;
    composeSendBtn.disabled = !enabled || sendingReply;
    composeInput.placeholder = enabled
      ? "Reply to this conversation..."
      : "Select a user to reply...";
  }

  async function loadMessages(userId) {
    messagesEl.innerHTML = '<p class="support-empty">Loading messages...</p>';
    try {
      const response = await fetch(`/api/chat/support/messages/${userId}`);
      if (!response.ok) {
        throw new Error("Failed to load support messages");
      }
      const payload = await response.json();
      renderMessages(payload);
      await loadThreads(userId);
    } catch (_error) {
      messagesEl.innerHTML = '<p class="support-empty">Unable to load support messages.</p>';
    }
  }

  async function loadThreads(preferredUserId = null) {
    userListEl.innerHTML = '<p class="support-empty">Loading support requests...</p>';
    try {
      const response = await fetch("/api/chat/support/threads");
      if (!response.ok) {
        throw new Error("Failed to load support threads");
      }
      const payload = await response.json();
      threads = payload.threads || [];
      if (!threads.length) {
        selectedUserId = null;
        titleEl.textContent = "Select a user";
        subtitleEl.textContent = "Choose a support conversation from the list.";
        messagesEl.innerHTML = '<p class="support-empty">Messages will appear here.</p>';
        setComposerEnabled(false);
        selectedSessionStatus = "none";
        if (endBtn) endBtn.disabled = true;
        renderThreadList();
        return;
      }

      const hasPreferred = preferredUserId && threads.some((t) => t.user_id === preferredUserId);
      selectedUserId = hasPreferred ? preferredUserId : (selectedUserId || threads[0].user_id);
      if (!threads.some((t) => t.user_id === selectedUserId)) {
        selectedUserId = threads[0].user_id;
      }
      renderThreadList();
      if (selectedUserId && !preferredUserId) {
        await loadMessages(selectedUserId);
      }
      const canInteract = selectedSessionStatus === "active" || selectedSessionStatus === "pending_admin";
      setComposerEnabled(Boolean(selectedUserId && canInteract));
    } catch (_error) {
      userListEl.innerHTML = '<p class="support-empty">Unable to load support requests.</p>';
      setComposerEnabled(false);
      selectedSessionStatus = "none";
      if (endBtn) endBtn.disabled = true;
    }
  }

  async function sendReply(message) {
    if (!selectedUserId || !message.trim()) return false;
    sendingReply = true;
    setComposerEnabled(true);

    try {
      const response = await fetch(`/api/chat/support/messages/${selectedUserId}/reply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sender: "admin",
          channel: "support",
          message: message.trim()
        })
      });
      if (!response.ok) {
        throw new Error("Failed to send reply");
      }
      composeInput.value = "";
      await loadMessages(selectedUserId);
      return true;
    } catch (_error) {
      subtitleEl.textContent = "Unable to send reply. Please try again.";
      return false;
    } finally {
      sendingReply = false;
      setComposerEnabled(Boolean(selectedUserId));
      composeInput?.focus();
    }
  }

  function startPolling() {
    if (pollingTimer) return;
    pollingTimer = window.setInterval(() => {
      if (selectedUserId) {
        loadMessages(selectedUserId);
      } else {
        loadThreads();
      }
    }, 15000);
  }

  if (refreshBtn) {
    refreshBtn.addEventListener("click", async () => {
      if (selectedUserId) {
        await loadMessages(selectedUserId);
      } else {
        await loadThreads();
      }
      await inlineNotice(refreshBtn, "Refreshed", "info", 1500);
    });
  }

  if (endBtn) {
    endBtn.addEventListener("click", async () => {
      if (!selectedUserId) return;
      try {
        const response = await fetch(`/api/chat/support/messages/${selectedUserId}/end`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
        });
        if (!response.ok) {
          throw new Error("Failed to end chat");
        }
        await loadMessages(selectedUserId);
        await inlineNotice(endBtn, "Chat ended");
      } catch (_error) {
        subtitleEl.textContent = "Unable to end chat right now.";
      }
    });
  }

  if (composeForm && composeInput) {
    composeForm.addEventListener("submit", (event) => {
      event.preventDefault();
      if (!selectedUserId || sendingReply) return;
      sendReply(composeInput.value || "").then((sent) => {
        if (sent) return inlineNotice(composeSendBtn, "Sent");
        return null;
      });
    });
  }

  setComposerEnabled(false);
  startPolling();
  loadThreads();
})();
