(function () {
  var root = document.querySelector("[data-chat-widget]");
  if (!root) return;

  var panel = root.querySelector("[data-chat-panel]");
  var toggle = root.querySelector("[data-chat-toggle]");
  var minimize = root.querySelector("[data-chat-minimize]");
  var modeBtn = root.querySelector("[data-chat-mode]");
  var body = root.querySelector("[data-chat-body]");
  var quick = root.querySelector("[data-chat-quick]");
  var form = root.querySelector("[data-chat-form]");
  var input = root.querySelector("[data-chat-input]");
  var statusEl = root.querySelector("[data-chat-status]");
  var unreadEl = root.querySelector("[data-chat-unread]");
  var tabs = root.querySelectorAll("[data-chat-tab]");

  var authenticated = root.getAttribute("data-authenticated") === "true";
  var mode = "guided";
  var aiAvailable = false;
  var tab = "assistant";
  var supportActive = false;
  var supportSeen = {};
  var supportPoll = null;
  var unread = 0;
  var dockTimer = null;
  var DOCK_MS = 10000;
  var welcomeShownKey = "ft_chat_welcome_v3";
  var openKey = "ft_chat_open";
  var ICONS = {
    wallet: "fa-wallet",
    book: "fa-book",
    list: "fa-list-ul",
    chart: "fa-chart-column",
    pie: "fa-chart-pie",
    plus: "fa-plus",
    help: "fa-circle-question",
    headset: "fa-headset",
    key: "fa-key",
    calendar: "fa-calendar-days",
    card: "fa-credit-card",
    bank: "fa-building-columns",
    coins: "fa-coins",
    activity: "fa-arrows-rotate",
    bell: "fa-bell",
    bulb: "fa-lightbulb",
    search: "fa-magnifying-glass",
  };

  function csrf() {
    return window.FinTrack && window.FinTrack.csrfToken
      ? window.FinTrack.csrfToken()
      : "";
  }

  function toast(msg, type) {
    if (window.FinTrack && window.FinTrack.toast) {
      window.FinTrack.toast(msg, type || "");
    }
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function iconClass(name) {
    return ICONS[name] || "fa-circle";
  }

  function money(value) {
    if (window.FTFormat) return FTFormat.formatINR(value);
    var n = Number(value || 0);
    var abs = Math.abs(n).toLocaleString("en-IN", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
    return (n < 0 ? "-₹" : "₹") + abs;
  }

  function clock(dated) {
    var time = new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    return dated ? "Today, " + time : time;
  }

  function dismissSuggestions() {
    if (!body) return;
    body.querySelectorAll(".ft-chat__suggest, .ft-chat__row.is-menu").forEach(function (node) {
      node.remove();
    });
  }

  function scrollToLatest() {
    if (!body) return;
    var pin = function () {
      body.scrollTop = body.scrollHeight;
    };
    pin();
    requestAnimationFrame(function () {
      pin();
      requestAnimationFrame(pin);
    });
    window.setTimeout(pin, 60);
  }

  function isPanelOpen() {
    return panel && !panel.hidden;
  }

  function clearDockTimer() {
    if (dockTimer) {
      window.clearTimeout(dockTimer);
      dockTimer = null;
    }
  }

  function dockBubble() {
    if (isPanelOpen()) return;
    root.classList.add("is-docked");
    clearDockTimer();
  }

  function scheduleDock() {
    clearDockTimer();
    if (isPanelOpen()) return;
    dockTimer = window.setTimeout(dockBubble, DOCK_MS);
  }

  function expandBubble() {
    root.classList.remove("is-docked");
    scheduleDock();
  }

  function setUnread(n) {
    unread = Math.max(0, n);
    if (!unreadEl) return;
    if (unread > 0 && panel.hidden) {
      unreadEl.hidden = false;
      unreadEl.textContent = unread > 9 ? "9+" : String(unread);
      expandBubble();
    } else {
      unreadEl.hidden = true;
    }
  }

  function updateStatus() {
    if (!statusEl) return;
    if (tab === "support") {
      statusEl.textContent = supportActive ? "Live support · Connected" : "Online · Live support ready";
    } else {
      statusEl.textContent = mode === "ai"
        ? "Online · AI mode"
        : "Online · Here to help with your finances";
    }
    if (modeBtn) {
      modeBtn.classList.toggle("is-on", mode === "ai");
      modeBtn.disabled = !aiAvailable && mode !== "ai";
      modeBtn.title = aiAvailable
        ? mode === "ai"
          ? "Switch to Guided"
          : "Switch to AI mode"
        : "AI unavailable (set OPENAI_API_KEY)";
    }
  }

  function bindQuick(btn, item) {
    btn.addEventListener("click", function () {
      if (item.id === "end_support") {
        endSupport();
        return;
      }
      if (tab === "support") {
        sendSupport(item.label || item.id);
      } else {
        sendAssistant({
          quick_id: item.id,
          label: item.prompt || item.label,
          message: item.message || null,
        });
      }
    });
  }

  function appendMessage(text, sender, opts) {
    opts = opts || {};
    if (!body) return;
    if (!text && !opts.card && !opts.suggestions && !opts.menu) return;

    var row = document.createElement("div");
    row.className = "ft-chat__row is-" + (sender || "bot");

    if (sender === "bot" || sender === "admin") {
      var av = document.createElement("span");
      av.className = "ft-chat__row-avatar";
      av.innerHTML = '<i class="fa-solid fa-chart-line" aria-hidden="true"></i>';
      row.appendChild(av);
    }

    var stack = document.createElement("div");
    stack.className = "ft-chat__stack";

    if (text) {
      var bubble = document.createElement("div");
      bubble.className = "ft-chat__msg";
      bubble.textContent = text;
      stack.appendChild(bubble);
    }

    if (opts.card) {
      stack.appendChild(renderCard(opts.card));
    }

    if (opts.suggestions && opts.suggestions.length) {
      stack.appendChild(renderSuggestions(opts.suggestions));
    }

    if (!opts.menu) {
      var time = document.createElement("span");
      time.className = "ft-chat__time";
      time.innerHTML = sender === "user"
        ? escapeHtml(clock()) + ' <i class="fa-solid fa-check" aria-hidden="true"></i>'
        : escapeHtml(clock(!!opts.dated));
      stack.appendChild(time);
    }

    row.appendChild(stack);
    body.appendChild(row);

    if (opts.menu) {
      var menuRow = document.createElement("div");
      menuRow.className = "ft-chat__row is-menu";
      menuRow.appendChild(renderMenu(opts.menu));
      body.appendChild(menuRow);
    }

    if (opts.stay) body.scrollTop = 0;
    else scrollToLatest();
  }

  function renderMenu(menu) {
    var wrap = document.createElement("div");
    wrap.className = "ft-chat__menu";
    wrap.innerHTML =
      '<div class="ft-chat__menu-head"><div><strong>' +
      escapeHtml(menu.title || "Things I can help you with") +
      "</strong><p>" +
      escapeHtml(menu.subtitle || "Quick actions to get started.") +
      '</p></div><button type="button" class="ft-chat__suggest-close" aria-label="Dismiss suggestions">' +
      '<i class="fa-solid fa-xmark" aria-hidden="true"></i></button></div>';
    wrap.querySelector("button").addEventListener("click", function () {
      var row = wrap.closest(".ft-chat__row");
      if (row) row.remove();
      else wrap.remove();
    });

    var groups = menu.groups || [];
    var i = 0;
    while (i < groups.length) {
      var group = groups[i];
      var next = groups[i + 1];
      if (group.layout === "stack" && next && next.layout === "stack") {
        var split = document.createElement("div");
        split.className = "ft-chat__menu-split";
        split.appendChild(renderMenuGroup(group));
        split.appendChild(renderMenuGroup(next));
        wrap.appendChild(split);
        i += 2;
        continue;
      }
      wrap.appendChild(renderMenuGroup(group));
      i += 1;
    }

    if (menu.examples && menu.examples.length) {
      var ask = document.createElement("div");
      ask.className = "ft-chat__ask";
      var quotes = menu.examples.map(function (ex) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = "“" + (ex.label || ex.id) + "”";
        bindQuick(btn, ex);
        return btn;
      });
      var copy = document.createElement("div");
      copy.innerHTML = "<strong>Or just ask in your own words</strong>";
      var line = document.createElement("p");
      quotes.forEach(function (btn, idx) {
        if (idx) line.appendChild(document.createTextNode(" "));
        line.appendChild(btn);
      });
      copy.appendChild(line);
      ask.innerHTML =
        '<span class="ft-chat__ask-ico"><i class="fa-solid fa-magnifying-glass" aria-hidden="true"></i></span>';
      ask.appendChild(copy);
      wrap.appendChild(ask);
    }
    return wrap;
  }

  function renderMenuGroup(group) {
    var block = document.createElement("section");
    block.className = "ft-chat__block";
    block.innerHTML =
      '<div class="ft-chat__block-head"><span class="ft-chat__block-ico"><i class="fa-solid ' +
      iconClass(group.icon) +
      '" aria-hidden="true"></i></span><div><strong>' +
      escapeHtml(group.title || "") +
      "</strong>" +
      (group.blurb
        ? "<span>" + escapeHtml(group.blurb) + "</span>"
        : "") +
      "</div></div>";
    var actions = group.actions || [];
    if (group.layout === "stack") {
      actions.forEach(function (item) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "ft-chat__stack-btn";
        btn.innerHTML =
          '<i class="fa-solid ' + iconClass(item.icon) + '" aria-hidden="true"></i>' +
          "<span>" + escapeHtml(item.label || item.id) + "</span>" +
          '<i class="fa-solid fa-chevron-right ft-chat__chev" aria-hidden="true"></i>';
        bindQuick(btn, item);
        block.appendChild(btn);
      });
      return block;
    }
    var pills = document.createElement("div");
    pills.className = "ft-chat__pills";
    actions.forEach(function (item) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "ft-chat__pill";
      btn.innerHTML =
        '<i class="fa-solid ' + iconClass(item.icon) + ' ft-chat__pill-ico" aria-hidden="true"></i>' +
        '<span class="ft-chat__pill-label">' + escapeHtml(item.label || item.id) + "</span>" +
        '<i class="fa-solid fa-chevron-right ft-chat__chev" aria-hidden="true"></i>';
      bindQuick(btn, item);
      pills.appendChild(btn);
    });
    block.appendChild(pills);
    return block;
  }

  function renderSuggestions(items) {
    var wrap = document.createElement("div");
    wrap.className = "ft-chat__suggest";
    wrap.innerHTML =
      '<div class="ft-chat__suggest-head"><strong>Here are some things you can do</strong>' +
      '<button type="button" class="ft-chat__suggest-close" aria-label="Dismiss suggestions">' +
      '<i class="fa-solid fa-xmark" aria-hidden="true"></i></button></div>';
    wrap.querySelector("button").addEventListener("click", function () {
      wrap.remove();
    });
    var grid = document.createElement("div");
    grid.className = "ft-chat__suggest-grid";
    items.forEach(function (item) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "ft-chat__action";
      btn.innerHTML =
        '<span class="ft-chat__action-ico"><i class="fa-solid ' +
        iconClass(item.icon) +
        '" aria-hidden="true"></i></span><span class="ft-chat__action-label">' +
        escapeHtml(item.label || item.id) +
        "</span>";
      bindQuick(btn, item);
      grid.appendChild(btn);
    });
    wrap.appendChild(grid);
    return wrap;
  }

  function renderCard(card) {
    var el = document.createElement("div");
    el.className = "ft-chat__card";
    if (card.type === "balances") {
      el.innerHTML =
        '<div class="ft-chat__card-kicker"><i class="fa-solid fa-wallet" aria-hidden="true"></i> ' +
        escapeHtml(card.title || "Total balance") +
        '</div><div class="ft-chat__card-total">' +
        escapeHtml(money(card.total)) +
        "</div>";
      (card.rows || []).forEach(function (row) {
        el.appendChild(cardRow(row.name, "", row.amount, row.icon || "bank", "neutral"));
      });
      if (card.footnote) {
        var note = document.createElement("p");
        note.className = "ft-chat__card-meta";
        note.textContent = card.footnote;
        el.appendChild(note);
      }
      return el;
    }

    if (card.type === "summary") {
      el.innerHTML =
        '<div class="ft-chat__card-kicker"><i class="fa-solid fa-chart-column" aria-hidden="true"></i> ' +
        escapeHtml(card.title || "Summary") +
        "</div>";
      var grid = document.createElement("div");
      grid.className = "ft-chat__summary";
      (card.items || []).forEach(function (item) {
        var cell = document.createElement("div");
        var shown = item.value_label != null ? item.value_label : money(item.value);
        cell.innerHTML =
          "<span>" + escapeHtml(item.label) + "</span><strong class=\"ft-chat__amt is-" +
          escapeHtml(item.tone || "neutral") +
          '">' +
          escapeHtml(String(shown)) +
          "</strong>";
        grid.appendChild(cell);
      });
      el.appendChild(grid);
      return el;
    }

    el.innerHTML =
      '<div class="ft-chat__card-kicker">' + escapeHtml(card.title || "Details") + "</div>";
    if (card.total != null) {
      var total = document.createElement("div");
      total.className = "ft-chat__card-total";
      total.textContent = money(card.total);
      el.appendChild(total);
    }
    (card.rows || []).forEach(function (row) {
      el.appendChild(cardRow(row.label, row.meta, row.amount, row.icon, row.tone));
    });
    return el;
  }

  function cardRow(label, meta, amount, icon, tone) {
    var row = document.createElement("div");
    row.className = "ft-chat__card-row";
    var amt = amount == null ? "" : money(amount);
    row.innerHTML =
      '<span class="ft-chat__card-ico"><i class="fa-solid ' +
      iconClass(icon || "bank") +
      '" aria-hidden="true"></i></span><div><strong>' +
      escapeHtml(label || "") +
      "</strong>" +
      (meta ? '<span class="ft-chat__card-meta">' + escapeHtml(meta) + "</span>" : "") +
      '</div><span class="ft-chat__amt is-' +
      escapeHtml(tone || "neutral") +
      '">' +
      escapeHtml(amt) +
      "</span>";
    return row;
  }

  function showTyping(on) {
    var existing = body && body.querySelector(".ft-chat__typing");
    if (existing) {
      var typingRow = existing.closest(".ft-chat__row");
      if (typingRow) typingRow.remove();
    }
    if (!on || !body) return;
    var row = document.createElement("div");
    row.className = "ft-chat__row is-bot";
    row.innerHTML =
      '<span class="ft-chat__row-avatar"><i class="fa-solid fa-chart-line" aria-hidden="true"></i></span>' +
      '<div class="ft-chat__stack"><div class="ft-chat__typing" aria-label="Thinking"><span></span><span></span><span></span></div></div>';
    body.appendChild(row);
    scrollToLatest();
  }

  function renderQuick(items) {
    if (!quick) return;
    quick.innerHTML = "";
    (items || []).slice(0, 3).forEach(function (item) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "ft-chat__chip";
      btn.innerHTML =
        '<i class="fa-solid ' + iconClass(item.icon) + '" aria-hidden="true"></i>' +
        escapeHtml(item.label || item.id);
      bindQuick(btn, item);
      quick.appendChild(btn);
    });
    scrollToLatest();
  }

  function openPanel() {
    root.hidden = false;
    panel.hidden = false;
    toggle.classList.add("is-open");
    toggle.setAttribute("aria-expanded", "true");
    root.classList.remove("is-docked");
    clearDockTimer();
    setUnread(0);
    try {
      sessionStorage.setItem(openKey, "1");
    } catch (_e) {}
    if (tab === "support") syncSupport({ initial: true });
    if (input) input.focus();
    scrollToLatest();
  }

  function closePanel() {
    panel.hidden = true;
    toggle.classList.remove("is-open");
    toggle.setAttribute("aria-expanded", "false");
    try {
      sessionStorage.removeItem(openKey);
    } catch (_e) {}
    scheduleDock();
  }

  function switchTab(next) {
    tab = next === "support" ? "support" : "assistant";
    tabs.forEach(function (t) {
      var active = t.getAttribute("data-chat-tab") === tab;
      t.classList.toggle("is-active", active);
      t.setAttribute("aria-selected", active ? "true" : "false");
    });
    body.innerHTML = "";
    if (tab === "assistant") {
      stopSupportPoll();
      bootstrap({ reuseWelcome: true });
    } else {
      appendMessage(
        "Live support connects you with an admin. Send a message or pick a shortcut.",
        "bot"
      );
      renderQuick([
        { id: "support_access", label: "Account access", icon: "help" },
        { id: "support_tx", label: "Wrong transaction", icon: "list" },
        { id: "support_other", label: "Something else", icon: "headset" },
      ]);
      syncSupport({ initial: true });
    }
    updateStatus();
  }

  async function bootstrap(opts) {
    opts = opts || {};
    try {
      var res = await fetch("/api/chat/bot/bootstrap");
      var data = await res.json();
      mode = data.mode || "guided";
      aiAvailable = !!data.ai_available;
      updateStatus();

      var already = false;
      try {
        already = sessionStorage.getItem(welcomeShownKey) === "1";
      } catch (_e) {}

      if (!opts.reuseWelcome || !body.childElementCount) {
        body.innerHTML = "";
        appendMessage(data.welcome || "Hello! How can I help?", "bot", {
          menu: data.menu || null,
          suggestions: data.suggestions || [],
          dated: true,
          stay: true,
        });
        try {
          sessionStorage.setItem(welcomeShownKey, "1");
        } catch (_e2) {}
      } else if (!already) {
        appendMessage(data.welcome || "Hello! How can I help?", "bot", {
          menu: data.menu || null,
          suggestions: data.suggestions || [],
          dated: true,
          stay: true,
        });
        try {
          sessionStorage.setItem(welcomeShownKey, "1");
        } catch (_e3) {}
      }

      renderQuick(data.quick_replies || []);

      if (!already && authenticated) {
        expandBubble();
      }
    } catch (_err) {
      appendMessage("Assistant is temporarily unavailable.", "system");
    }
  }

  async function sendAssistant(payload) {
    var label = payload.label || payload.message || payload.quick_id || "";
    dismissSuggestions();
    if (label) appendMessage(label, "user");
    showTyping(true);
    renderQuick([]);
    try {
      var res = await fetch("/api/chat/bot", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrf(),
        },
        body: JSON.stringify({
          message: payload.message || null,
          quick_id: payload.quick_id || null,
          set_mode: payload.set_mode || null,
        }),
      });
      var data = await res.json();
      showTyping(false);
      if (!res.ok) throw new Error(data.detail || "Request failed");
      mode = data.mode || mode;
      aiAvailable = data.ai_available != null ? !!data.ai_available : aiAvailable;
      updateStatus();
      appendMessage(data.reply || "", "bot", {
        card: data.card || null,
        suggestions: data.suggestions || null,
        menu: data.menu || null,
      });
      renderQuick(data.quick_replies || []);
      scrollToLatest();

      if (data.escalate_support) {
        switchTab("support");
        if (data.support_prefill) {
          await sendSupport(data.support_prefill);
        }
      }

      if (panel.hidden) setUnread(unread + 1);
    } catch (err) {
      showTyping(false);
      appendMessage(err.message || "Something went wrong.", "system");
    }
  }

  async function sendSupport(text) {
    var message = String(text || "").trim();
    if (!message) return;
    appendMessage(message, "user");
    try {
      var bodyPayload = {
        sender: "user",
        channel: "support",
        message: message,
      };
      if (!authenticated) {
        var name = window.prompt("Your name for support", "") || "";
        if (!name.trim()) {
          appendMessage("Name is required for guest support messages.", "system");
          return;
        }
        bodyPayload.guest_name = name.trim();
      }
      var res = await fetch("/api/chat/log", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrf(),
        },
        body: JSON.stringify(bodyPayload),
      });
      var data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Send failed");
      if (data.message_id) supportSeen[String(data.message_id)] = true;
      appendMessage("Thanks — an admin will reply here.", "bot");
      await syncSupport({ initial: false });
      startSupportPoll();
    } catch (err) {
      appendMessage(err.message || "Could not reach support.", "system");
    }
  }

  async function syncSupport(opts) {
    opts = opts || {};
    try {
      var res = await fetch("/api/chat/support/my/messages");
      if (!res.ok) return;
      var data = await res.json();
      var session = data.session || {};
      var status = session.status || "none";
      supportActive = status === "pending_admin" || status === "active";
      updateStatus();

      (data.messages || []).forEach(function (m) {
        var id = String(m._id || "");
        if (!id || supportSeen[id]) return;
        supportSeen[id] = true;
        if (m.sender === "user" && opts.initial) {
          appendMessage(m.message, "user");
          return;
        }
        if (m.sender === "user") return;
        if (m.sender === "admin") {
          appendMessage(m.message, "admin");
          if (!opts.initial && panel.hidden) setUnread(unread + 1);
          return;
        }
        appendMessage(m.message, "system");
      });

      if (supportActive) {
        renderQuick([{ id: "end_support", label: "End chat", icon: "headset" }]);
        startSupportPoll();
      }
    } catch (_err) {}
  }

  async function endSupport() {
    try {
      await fetch("/api/chat/support/end", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf() },
      });
    } catch (_e) {}
    supportActive = false;
    stopSupportPoll();
    appendMessage("Support chat ended.", "system");
    renderQuick([
      { id: "support_access", label: "Account access", icon: "help" },
      { id: "support_tx", label: "Wrong transaction", icon: "list" },
      { id: "support_other", label: "Something else", icon: "headset" },
    ]);
    updateStatus();
  }

  function startSupportPoll() {
    if (supportPoll) return;
    supportPoll = window.setInterval(function () {
      if (tab !== "support") return;
      syncSupport({ initial: false });
    }, 5000);
  }

  function stopSupportPoll() {
    if (!supportPoll) return;
    clearInterval(supportPoll);
    supportPoll = null;
  }

  root.addEventListener("mouseenter", expandBubble);
  root.addEventListener("focusin", expandBubble);

  toggle.addEventListener("click", function () {
    if (panel.hidden) openPanel();
    else closePanel();
  });

  if (minimize) {
    minimize.addEventListener("click", closePanel);
  }

  tabs.forEach(function (t) {
    t.addEventListener("click", function () {
      switchTab(t.getAttribute("data-chat-tab"));
    });
  });

  if (modeBtn) {
    modeBtn.addEventListener("click", function () {
      if (!aiAvailable && mode !== "ai") {
        toast("AI mode needs OPENAI_API_KEY on the server", "error");
        return;
      }
      var next = mode === "ai" ? "guided" : "ai";
      sendAssistant({ set_mode: next, label: next === "ai" ? "Switch to AI mode" : "Switch to Guided" });
    });
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var value = (input.value || "").trim();
    if (!value) return;
    input.value = "";
    autoSize();
    if (tab === "support") sendSupport(value);
    else sendAssistant({ message: value });
  });

  function autoSize() {
    if (!input) return;
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 96) + "px";
  }

  input.addEventListener("input", autoSize);
  input.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  function maybeOpenFromHash() {
    if (window.location.hash === "#support-chat") {
      openPanel();
      switchTab("support");
    }
  }

  window.addEventListener("ft:chat-open", function (event) {
    openPanel();
    var detail = (event && event.detail) || {};
    if (detail.tab === "support") switchTab("support");
    if (detail.message) {
      if (detail.tab === "support") sendSupport(detail.message);
      else sendAssistant({ message: detail.message });
    }
  });

  root.hidden = false;
  root.classList.add("is-docked");
  bootstrap();
  maybeOpenFromHash();
  try {
    if (sessionStorage.getItem(openKey) === "1") openPanel();
  } catch (_e) {}
})();
