// Dashboard charts rendering.

(function () {
  const dataEl = document.getElementById("dashboard-data");
  if (!dataEl) return;

  const splitList = (value) => {
    if (!value) return [];
    return value.split("|").filter((v) => v !== "");
  };

  const splitNumbers = (value) => splitList(value).map((v) => Number(v));

  const dailyLabels = splitList(dataEl.dataset.dailyLabels);
  const dailyNet = splitNumbers(dataEl.dataset.dailyNet);
  const dailyIncome = splitNumbers(dataEl.dataset.dailyIncome);
  const dailyExpense = splitNumbers(dataEl.dataset.dailyExpense);

  const monthlyLabels = splitList(dataEl.dataset.monthlyLabels);
  const monthlyIncome = splitNumbers(dataEl.dataset.monthlyIncome);
  const monthlyExpense = splitNumbers(dataEl.dataset.monthlyExpense);

  const categoryLabels = splitList(dataEl.dataset.categoryLabels);
  const categoryTotals = splitNumbers(dataEl.dataset.categoryTotals);

  const spendingCtx = document.getElementById("spendingCategoryChart");
  if (spendingCtx && categoryTotals.length > 0) {
    new Chart(spendingCtx, {
      type: "doughnut",
      data: {
        labels: categoryLabels,
        datasets: [
          {
            data: categoryTotals,
            backgroundColor: ["#0ea5e9", "#22c55e", "#f97316", "#a855f7", "#eab308"],
            borderColor: "#f8fafc",
            borderWidth: 2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "62%",
        plugins: {
          legend: { position: "bottom" },
        },
      },
    });
  }

  const cashflowCtx = document.getElementById("cashflowChart");
  if (cashflowCtx) {
    new Chart(cashflowCtx, {
      type: "line",
      data: {
        labels: dailyLabels,
        datasets: [
          {
            label: "Net",
            data: dailyNet,
            borderColor: "#0f766e",
            backgroundColor: "rgba(15, 118, 110, 0.15)",
            tension: 0.35,
            fill: true,
          },
          {
            label: "Income",
            data: dailyIncome,
            borderColor: "#16a34a",
            backgroundColor: "rgba(22, 163, 74, 0.08)",
            tension: 0.35,
            fill: false,
          },
          {
            label: "Expense",
            data: dailyExpense,
            borderColor: "#dc2626",
            backgroundColor: "rgba(220, 38, 38, 0.08)",
            tension: 0.35,
            fill: false,
          },
        ],
      },
      options: {
        responsive: true,
        plugins: {
          legend: { position: "top" },
        },
        scales: {
          y: { beginAtZero: true },
        },
      },
    });
  }

  const incomeExpenseCtx = document.getElementById("incomeExpenseChart");
  if (incomeExpenseCtx) {
    new Chart(incomeExpenseCtx, {
      type: "bar",
      data: {
        labels: monthlyLabels,
        datasets: [
          {
            label: "Income",
            data: monthlyIncome,
            backgroundColor: "rgba(22, 163, 74, 0.6)",
          },
          {
            label: "Expense",
            data: monthlyExpense,
            backgroundColor: "rgba(220, 38, 38, 0.6)",
          },
        ],
      },
      options: {
        responsive: true,
        plugins: {
          legend: { position: "top" },
        },
        scales: {
          y: { beginAtZero: true },
        },
      },
    });
  }
})();
