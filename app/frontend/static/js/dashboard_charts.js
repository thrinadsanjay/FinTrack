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
      type: "bar",
      data: {
        labels: dailyLabels,
        datasets: [
          {
            label: "Income",
            data: dailyIncome,
            backgroundColor: "rgba(22, 163, 74, 0.65)",
            borderRadius: 5,
            maxBarThickness: 16,
          },
          {
            label: "Expense",
            data: dailyExpense,
            backgroundColor: "rgba(220, 38, 38, 0.65)",
            borderRadius: 5,
            maxBarThickness: 16,
          },
        ],
      },
      options: {
        responsive: true,
        plugins: {
          legend: { position: "top" },
        },
        scales: {
          x: { title: { display: true, text: "Date" } },
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
            backgroundColor: "rgba(22, 163, 74, 0.75)",
            borderColor: "rgba(22, 163, 74, 1)",
            borderWidth: 1,
            borderRadius: 6,
            maxBarThickness: 18,
          },
          {
            label: "Expense",
            data: monthlyExpense,
            backgroundColor: "rgba(220, 38, 38, 0.82)",
            borderColor: "rgba(220, 38, 38, 1)",
            borderWidth: 1,
            borderRadius: 6,
            maxBarThickness: 18,
          },
        ],
      },
      options: {
        responsive: true,
        plugins: {
          legend: { position: "top" },
        },
        scales: {
          x: {
            stacked: false,
          },
          y: { beginAtZero: true },
        },
      },
    });
  }
})();
