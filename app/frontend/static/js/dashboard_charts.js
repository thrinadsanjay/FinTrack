// Dashboard charts rendering.

(function () {
  const css = getComputedStyle(document.documentElement);
  const textColor = (css.getPropertyValue("--color-text") || "#0f172a").trim();
  const mutedColor = (css.getPropertyValue("--color-muted") || "#64748b").trim();
  const gridColor = "rgba(148, 163, 184, 0.18)";
  const doughnutPalette = ["#0f766e", "#2563eb", "#f59e0b", "#dc2626", "#7c3aed", "#0891b2"];

  const basePlugins = {
    legend: {
      labels: {
        color: textColor,
        boxWidth: 10,
        boxHeight: 10,
        usePointStyle: true,
        pointStyle: "circle",
        padding: 16,
        font: { size: 11, weight: "600" },
      },
    },
    tooltip: {
      backgroundColor: "rgba(15, 23, 42, 0.92)",
      titleColor: "#f8fafc",
      bodyColor: "#e2e8f0",
      padding: 10,
      cornerRadius: 10,
      displayColors: true,
    },
  };

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
            backgroundColor: doughnutPalette,
            borderColor: "rgba(248, 250, 252, 0.9)",
            borderWidth: 3,
            hoverOffset: 10,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "66%",
        layout: { padding: { top: 4, bottom: 4 } },
        plugins: {
          ...basePlugins,
          legend: {
            ...basePlugins.legend,
            position: "bottom",
          },
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
            backgroundColor: "rgba(13, 148, 136, 0.78)",
            borderColor: "rgba(15, 118, 110, 1)",
            borderWidth: 1,
            borderRadius: 7,
            maxBarThickness: 18,
          },
          {
            label: "Expense",
            data: dailyExpense,
            backgroundColor: "rgba(234, 88, 12, 0.75)",
            borderColor: "rgba(194, 65, 12, 1)",
            borderWidth: 1,
            borderRadius: 7,
            maxBarThickness: 18,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          ...basePlugins,
          legend: {
            ...basePlugins.legend,
            position: "top",
            align: "start",
          },
        },
        scales: {
          x: {
            ticks: { color: mutedColor, maxRotation: 0 },
            grid: { display: false },
            title: { display: true, text: "Date", color: mutedColor, font: { size: 11, weight: "600" } },
          },
          y: {
            beginAtZero: true,
            ticks: { color: mutedColor },
            grid: { color: gridColor },
          },
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
            backgroundColor: "rgba(14, 165, 164, 0.82)",
            borderColor: "rgba(13, 148, 136, 1)",
            borderWidth: 1,
            borderRadius: 7,
            maxBarThickness: 20,
          },
          {
            label: "Expense",
            data: monthlyExpense,
            backgroundColor: "rgba(239, 68, 68, 0.84)",
            borderColor: "rgba(220, 38, 38, 1)",
            borderWidth: 1,
            borderRadius: 7,
            maxBarThickness: 20,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          ...basePlugins,
          legend: {
            ...basePlugins.legend,
            position: "top",
            align: "start",
          },
        },
        scales: {
          x: {
            stacked: false,
            ticks: { color: mutedColor, maxRotation: 0 },
            grid: { display: false },
          },
          y: {
            beginAtZero: true,
            ticks: { color: mutedColor },
            grid: { color: gridColor },
          },
        },
      },
    });
  }
})();
