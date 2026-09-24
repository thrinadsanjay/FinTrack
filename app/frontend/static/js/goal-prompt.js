(function () {
  var dialog = document.querySelector("[data-goal-prompt]");
  if (!dialog || typeof dialog.showModal !== "function") return;

  var ask = dialog.querySelector('[data-gp-step="ask"]');
  var pick = dialog.querySelector('[data-gp-step="pick"]');

  function close() {
    dialog.close();
    dialog.remove();
  }

  dialog.querySelectorAll("[data-gp-no]").forEach(function (btn) {
    btn.addEventListener("click", close);
  });

  var yes = dialog.querySelector("[data-gp-yes]");
  if (yes) {
    yes.addEventListener("click", function () {
      ask.hidden = true;
      pick.hidden = false;
      var select = pick.querySelector("select");
      if (select) select.focus();
    });
  }

  dialog.addEventListener("cancel", function (event) {
    event.preventDefault();
    close();
  });

  dialog.showModal();
})();
