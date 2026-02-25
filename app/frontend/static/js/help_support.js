(() => {
  const page = document.querySelector('[data-help-page]');
  if (!page) return;
  document.body.classList.add("help-support-locked");

  const tiles = Array.from(page.querySelectorAll('[data-help-target]'));
  const panels = Array.from(page.querySelectorAll('[data-help-panel]'));

  function activatePanel(name) {
    tiles.forEach((tile) => tile.classList.toggle('active', tile.dataset.helpTarget === name));
    panels.forEach((panel) => panel.classList.toggle('active', panel.dataset.helpPanel === name));
  }

  tiles.forEach((tile) => {
    tile.addEventListener('click', () => activatePanel(tile.dataset.helpTarget));
  });

  const chatBox = page.querySelector('[data-chat-box]');
  const chatToggle = page.querySelector('[data-chat-toggle]');
  const chatClose = page.querySelector('[data-chat-close]');
  const openChatBtn = page.querySelector('[data-open-chat]');

  function showChat(show) {
    if (!chatBox) return;
    chatBox.hidden = !show;
  }

  if (chatToggle) {
    chatToggle.addEventListener('click', () => showChat(chatBox?.hidden));
  }

  if (chatClose) {
    chatClose.addEventListener('click', () => showChat(false));
  }

  if (openChatBtn) {
    openChatBtn.addEventListener('click', () => {
      activatePanel('chat');
      showChat(true);
    });
  }

  if (window.location.hash === '#support-chat') {
    activatePanel('chat');
    showChat(true);
  }

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') showChat(false);
  });

  document.addEventListener('click', (event) => {
    if (!chatBox || chatBox.hidden) return;
    if (chatBox.contains(event.target)) return;
    if (chatToggle && chatToggle.contains(event.target)) return;
    showChat(false);
  });

  window.addEventListener("beforeunload", () => {
    document.body.classList.remove("help-support-locked");
  });
})();
