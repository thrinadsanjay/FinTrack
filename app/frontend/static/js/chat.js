document.addEventListener("DOMContentLoaded", () => {
  const chatBody = document.getElementById("chatBody");
  const chatOptions = document.getElementById("chatOptions");
  const chatForm = document.getElementById("chatForm");
  const chatInput = document.getElementById("chatInput");
  const typingIndicator = document.getElementById("typingIndicator");
  const helpPage = document.querySelector("[data-help-page]");
  const isAuthenticated = helpPage?.dataset.userAuthenticated === "true";

  if (!chatBody || !chatOptions || !chatForm || !chatInput) return;

  const BOT_RESPONSES = {
    login: "For login issues, use Forgot Password from login page first.",
    transaction: "For transaction errors, verify account, amount, and date. Then retry once.",
    recurring: "For recurring setup, check active schedule and next run date.",
  };

  let guestName = "";
  let pendingInputMode = null; // guest_name | support_issue | null
  let supportSessionActive = false;
  let seenMessageIds = new Set();
  let supportPollTimer = null;
  let introRendered = false;

  function addMessage(text, sender = "bot") {
    const row = document.createElement("div");
    row.className = `chat-message ${sender}`;
    row.textContent = text;
    chatBody.appendChild(row);
    chatBody.scrollTop = chatBody.scrollHeight;
  }

  function showTyping(callback) {
    if (!typingIndicator) {
      callback();
      return;
    }
    typingIndicator.hidden = false;
    setTimeout(() => {
      typingIndicator.hidden = true;
      callback();
    }, 450);
  }

  function renderButtons(buttons) {
    chatOptions.innerHTML = "";
    buttons.forEach((button) => {
      const el = document.createElement("button");
      el.type = "button";
      el.className = "chat-option-btn";
      el.textContent = button.label;
      el.addEventListener("click", button.onClick);
      chatOptions.appendChild(el);
    });
  }

  function renderRootOptions() {
    renderButtons([
      { label: "Login Issue", onClick: () => handleKnowledgeSelection("login", "Login Issue") },
      { label: "Transaction Error", onClick: () => handleKnowledgeSelection("transaction", "Transaction Error") },
      { label: "Recurring Setup", onClick: () => handleKnowledgeSelection("recurring", "Recurring Setup") },
      { label: "Talk to Support", onClick: () => connectToSupportDirect("Talk to Support") },
    ]);
  }

  function renderSatisfactionOptions() {
    renderButtons([
      {
        label: "Yes",
        onClick: () => {
          addMessage("Yes", "user");
          showTyping(() => {
            addMessage("Thanks for confirming. Happy to help.", "bot");
            renderRootOptions();
          });
        },
      },
      {
        label: "No",
        onClick: () => {
          addMessage("No", "user");
          beginSupportIntake();
        },
      },
    ]);
  }

  function renderEndChatOption() {
    renderButtons([
      {
        label: "End Chat",
        onClick: () => endSupportChat(),
      },
    ]);
  }

  function ensureIntro() {
    if (introRendered) return;
    introRendered = true;
    showTyping(() => {
      addMessage("Hi. Select an option below to continue.", "bot");
      renderRootOptions();
    });
  }

  function handleKnowledgeSelection(key, label) {
    addMessage(label, "user");
    showTyping(() => {
      addMessage(BOT_RESPONSES[key], "bot");
      addMessage("Is your issue resolved?", "bot");
      renderSatisfactionOptions();
    });
  }

  function connectToSupportDirect(label) {
    addMessage(label, "user");
    beginSupportIntake();
  }

  function beginSupportIntake() {
    if (!isAuthenticated && !guestName) {
      pendingInputMode = "guest_name";
      showTyping(() => {
        addMessage("Before we connect you, please share your name.", "bot");
      });
      return;
    }
    pendingInputMode = "support_issue";
    showTyping(() => {
      if (!isAuthenticated && guestName) {
        addMessage(`Thanks ${guestName}. Please describe your issue.`, "bot");
      } else {
        addMessage("Please describe your issue.", "bot");
      }
    });
  }

  async function logSupportMessage(text) {
    const payload = {
      sender: "user",
      channel: "support",
      message: text,
    };
    if (!isAuthenticated && guestName) {
      payload.guest_name = guestName;
    }
    const response = await fetch("/api/chat/log", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      throw new Error("Failed to send support message");
    }
    const data = await response.json();
    if (data?.message_id) {
      seenMessageIds.add(String(data.message_id));
    }
  }

  async function syncSupportMessages({ initial = false } = {}) {
    const response = await fetch("/api/chat/support/my/messages");
    if (!response.ok) return;
    const payload = await response.json();
    const session = payload.session || {};
    const status = session.status || "none";
    const isOpen = status === "pending_admin" || status === "active";
    supportSessionActive = isOpen;

    const messages = payload.messages || [];
    for (const message of messages) {
      const id = message._id;
      if (!id || seenMessageIds.has(id)) continue;
      seenMessageIds.add(id);

      if (message.sender === "user") {
        addMessage(message.message, "user");
        continue;
      }
      if (message.sender === "admin") {
        addMessage(`Admin: ${message.message}`, "bot");
        if (!initial) {
          notifyAdminReply();
        }
        continue;
      }
      if (message.sender === "system") {
        addMessage(message.message, "bot");
      }
    }

    if (supportSessionActive) {
      renderEndChatOption();
      startSupportPolling();
    } else {
      stopSupportPolling();
      if (pendingInputMode == null) {
        renderRootOptions();
      }
    }
  }

  function startSupportPolling() {
    if (supportPollTimer) return;
    supportPollTimer = window.setInterval(() => {
      if (!supportSessionActive) return;
      syncSupportMessages().catch(() => {});
    }, 5000);
  }

  function stopSupportPolling() {
    if (!supportPollTimer) return;
    clearInterval(supportPollTimer);
    supportPollTimer = null;
  }

  function notifyAdminReply() {
    if ("Notification" in window && document.hidden) {
      if (Notification.permission === "granted") {
        new Notification("Support replied", { body: "Open chat to view latest reply." });
      } else if (Notification.permission === "default") {
        Notification.requestPermission().catch(() => {});
      }
    }
  }

  async function beginSupportSessionWithIssue(issueText) {
    await logSupportMessage(issueText);
    pendingInputMode = null;
    showTyping(() => {
      addMessage("Thanks for the response. We are connecting you to Admin.", "bot");
      renderEndChatOption();
    });
    await syncSupportMessages({ initial: true });
  }

  async function endSupportChat() {
    if (!supportSessionActive) return;
    try {
      await fetch("/api/chat/support/end", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
    } catch (_error) {
      // no-op
    }
    supportSessionActive = false;
    pendingInputMode = null;
    stopSupportPolling();
    showTyping(() => {
      addMessage("Chat ended. You can start a new request anytime.", "bot");
      renderRootOptions();
    });
    await syncSupportMessages({ initial: true }).catch(() => {});
  }

  chatForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = chatInput.value.trim();
    if (!text) return;
    chatInput.value = "";

    if (pendingInputMode === "guest_name") {
      guestName = text;
      addMessage(text, "user");
      pendingInputMode = "support_issue";
      showTyping(() => {
        addMessage(`Thanks ${guestName}. Please describe your issue.`, "bot");
      });
      return;
    }

    if (pendingInputMode === "support_issue") {
      addMessage(text, "user");
      try {
        await beginSupportSessionWithIssue(text);
      } catch (_error) {
        showTyping(() => {
          addMessage("Unable to connect support right now. Please try again.", "bot");
          renderRootOptions();
        });
      }
      return;
    }

    if (supportSessionActive) {
      addMessage(text, "user");
      try {
        await logSupportMessage(text);
      } catch (_error) {
        showTyping(() => {
          addMessage("Unable to send message. Please retry.", "bot");
        });
      }
      return;
    }

    addMessage(text, "user");
    showTyping(() => {
      addMessage("Please select one of the options to continue.", "bot");
      renderRootOptions();
    });
  });

  async function initialize() {
    try {
      await syncSupportMessages({ initial: true });
    } catch (_error) {
      // no-op
    }
    if (!chatBody.children.length) {
      ensureIntro();
    }
  }

  initialize();
});
