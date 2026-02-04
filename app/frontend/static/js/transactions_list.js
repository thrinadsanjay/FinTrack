// Transactions list page helpers: account data + row menu toggle.

(function setAccountsData() {
  const dataList = document.getElementById("accounts-data");
  if (!dataList) return;
  const accounts = Array.from(dataList.querySelectorAll("li")).map((item) => ({
    id: item.dataset.id,
    name: item.dataset.name,
  }));
  window.ACCOUNTS = accounts;
})();

(function rowMenuToggle() {
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-menu-toggle]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const menu = btn.nextElementSibling;
        document.querySelectorAll(".row-menu").forEach((m) => {
          if (m !== menu) m.classList.remove("open");
        });
        if (menu) menu.classList.toggle("open");
      });
    });
    document.addEventListener("click", () => {
      document.querySelectorAll(".row-menu").forEach((m) => m.classList.remove("open"));
    });
  });
})();
