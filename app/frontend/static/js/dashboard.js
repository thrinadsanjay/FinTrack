(function () {
  var root = document.querySelector("[data-dashboard]");
  if (!root) return;

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var ACCOUNT_METALS = [
    { id: "ft-metal-gold", from: "#E8D08A", mid: "#C6A24A", to: "#8A6A22" },
    { id: "ft-metal-copper", from: "#D48A52", mid: "#B87333", to: "#7A431C" },
    { id: "ft-metal-rosegold", from: "#D9A8AE", mid: "#B76E79", to: "#7A3E48" },
    { id: "ft-metal-brass", from: "#D8C86C", mid: "#B5A642", to: "#6F641C" },
    { id: "ft-metal-bronze", from: "#C48A4C", mid: "#8C5A2E", to: "#5A3414" },
    { id: "ft-metal-champagne", from: "#E6D6B4", mid: "#C4B08A", to: "#8A7452" }
  ];
  var SPEND_METALS = [
    { id: "ft-spend-copper", from: "#E8A27B", mid: "#B86D3F", to: "#814326" },
    { id: "ft-spend-teal", from: "#8FC7B3", mid: "#4F8A79", to: "#315F54" },
    { id: "ft-spend-slate", from: "#A6B4C0", mid: "#586B7C", to: "#374754" },
    { id: "ft-spend-coral", from: "#F0AD8E", mid: "#DF8C62", to: "#A45D3D" },
    { id: "ft-spend-amber", from: "#EBCB82", mid: "#D6A14C", to: "#936B27" },
    { id: "ft-spend-purple", from: "#B9A3CF", mid: "#8C6FA8", to: "#5F4A75" },
    { id: "ft-spend-blue", from: "#A9C5DA", mid: "#6F9AB8", to: "#456A84" },
    { id: "ft-spend-rose", from: "#D9A8AE", mid: "#B76E79", to: "#7A3E48" }
  ];
  var ACCOUNT_COLORS = ACCOUNT_METALS.map(function (metal) { return metal.mid; });
  var SPEND_COLORS = SPEND_METALS.map(function (metal) { return metal.mid; });
  var R = 42;
  var C = 2 * Math.PI * R;

  function appendMetalDefs(svg, metals) {
    var ns = "http://www.w3.org/2000/svg";
    var defs = document.createElementNS(ns, "defs");
    metals.forEach(function (metal) {
      var gradient = document.createElementNS(ns, "linearGradient");
      gradient.setAttribute("id", metal.id);
      gradient.setAttribute("gradientUnits", "objectBoundingBox");
      gradient.setAttribute("x1", "0");
      gradient.setAttribute("y1", "0");
      gradient.setAttribute("x2", "1");
      gradient.setAttribute("y2", "1");
      [
        ["0%", metal.from],
        ["42%", metal.mid],
        ["100%", metal.to]
      ].forEach(function (pair) {
        var stop = document.createElementNS(ns, "stop");
        stop.setAttribute("offset", pair[0]);
        stop.setAttribute("stop-color", pair[1]);
        gradient.appendChild(stop);
      });
      defs.appendChild(gradient);
    });
    svg.appendChild(defs);
  }

  function metalStroke(metals, index) {
    return "url(#" + metals[index % metals.length].id + ")";
  }

  function cssVar(name, fallback) {
    var value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  }

  function parseJson(attr, fallback) {
    try {
      var data = JSON.parse(root.getAttribute(attr) || "");
      return data == null ? fallback : data;
    } catch (_err) {
      return fallback;
    }
  }

  function parseTrend() {
    var data = parseJson("data-trend", []);
    return Array.isArray(data) ? data : [];
  }

  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  function moneyLabel(value) {
    if (window.FTFormat) return FTFormat.formatINR(value, { space: true });
    return "₹ " + Number(value || 0).toLocaleString("en-IN", {
      maximumFractionDigits: 2,
      minimumFractionDigits: 2
    });
  }

  function balanceMoneyLabel(value) {
    return moneyLabel(value);
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (char) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char];
    });
  }

  function dayLabel(point) {
    if (point.date) {
      var parts = String(point.date).split("-");
      if (parts.length >= 3) {
        return Number(parts[2]) + " " + (MONTHS[Number(parts[1]) - 1] || "");
      }
    }
    return point.day ? String(point.day) : "";
  }

  function dailySeries(trend) {
    var byDay = {};
    var year;
    var month;
    (Array.isArray(trend) ? trend : []).forEach(function (point) {
      var date = String(point.date || "");
      var day = Number(point.day) || (date ? Number(date.slice(-2)) : 0);
      if (date.length >= 7) {
        year = Number(date.slice(0, 4));
        month = Number(date.slice(5, 7));
      }
      if (!day) return;
      byDay[day] = {
        day: day,
        date: date,
        income: Number(point.income || point.credit || 0),
        expense: Number(point.expense || point.debit || 0),
        label: ""
      };
    });
    if (!year || !month) {
      var now = new Date();
      year = now.getFullYear();
      month = now.getMonth() + 1;
    }
    var last = new Date(year, month, 0).getDate();
    var points = [];
    var day;
    for (day = 1; day <= last; day += 1) {
      var key = year + "-" + String(month).padStart(2, "0") + "-" + String(day).padStart(2, "0");
      var point = byDay[day] || {
        day: day,
        date: key,
        income: 0,
        expense: 0,
        label: ""
      };
      if (!point.date) point.date = key;
      point.label = day === 1 || day % 5 === 0 || day === last ? String(day) : "";
      points.push(point);
    }
    return points;
  }

  function monthlySeries() {
    var all = parseJson("data-monthly", []).map(function (item) {
      return {
        income: Number(item.income || 0),
        expense: Number(item.expense || 0),
        label: item.month_short || "",
        date: item.month_label || item.month || ""
      };
    });
    var active = all.filter(function (point) { return point.income || point.expense; });
    if (active.length && active.length <= 6) return active;
    return all;
  }

  function cashflowRange() {
    var select = root.querySelector("[data-cashflow-range]");
    if (select && select.value) return select.value;
    return root.getAttribute("data-cashflow-default") || "month";
  }

  function currentCashflowSeries() {
    var range = cashflowRange();
    if (
      cashflowWindowState.series &&
      cashflowWindowState.range === range
    ) {
      return cashflowWindowState.series;
    }
    if (range === "month" || range === "week") {
      var daily = dailySeries(parseTrend());
      if (daily.length) return daily;
    }
    var monthly = monthlySeries();
    if (range === "3m") return monthly.slice(-3);
    if (range === "6m") return monthly.slice(-6);
    return monthly.some(function (point) { return point.income || point.expense; }) ? monthly : [];
  }

  var spendUi = { circles: [], bound: false };
  var balanceUi = { circles: [] };
  var ACCOUNT_TYPES = {
    savings: "Savings",
    current: "Current",
    cash: "Cash",
    wallet: "Wallet",
    investment: "Investment",
    other: "Other",
    credit_card: "Card"
  };

  function highlightSpend(index) {
    spendUi.circles.forEach(function (circle, i) {
      var on = index === i;
      var idle = index < 0;
      circle.style.opacity = idle || on ? "1" : "0.38";
      circle.setAttribute("stroke-width", on ? "18" : "16");
    });
  }

  function highlightBalance(index) {
    balanceUi.circles.forEach(function (circle, i) {
      var on = index === i;
      var idle = index < 0;
      circle.style.opacity = idle || on ? "1" : "0.32";
      circle.setAttribute("stroke-width", on ? "13" : "11");
    });
    root.querySelectorAll("[data-balance-row]").forEach(function (row) {
      var slice = Number(row.getAttribute("data-balance-row"));
      row.classList.toggle("is-dim", index >= 0 && slice !== index);
      row.classList.toggle("is-on", index >= 0 && slice === index);
    });
  }

  function placeFloatTip(tip, clientX, clientY) {
    if (!tip) return;
    if (tip.parentNode !== document.body) document.body.appendChild(tip);
    tip.hidden = false;
    var w = tip.offsetWidth || 168;
    var h = tip.offsetHeight || 96;
    var left = clientX + 14;
    var top = clientY + 16;
    if (left + w > window.innerWidth - 8) left = clientX - w - 14;
    if (left < 8) left = 8;
    if (top + h > window.innerHeight - 8) top = clientY - h - 12;
    if (top < 8) top = 8;
    tip.style.left = left + "px";
    tip.style.top = top + "px";
  }

  function placeAnchorPop(pop, anchor) {
    if (!pop) return;
    if (pop.parentNode !== document.body) document.body.appendChild(pop);
    pop.hidden = false;
    pop.classList.add("is-open");
    pop.style.transform = "";
    var box = (anchor && anchor.getBoundingClientRect()) || { left: 16, top: 16, bottom: 16, width: 80 };
    var w = pop.offsetWidth || 320;
    var h = pop.offsetHeight || 220;
    var left = box.left;
    var top = box.bottom + 10;
    var place = "below";
    if (top + h > window.innerHeight - 8 && box.top - h - 10 >= 8) {
      top = box.top - h - 10;
      place = "above";
    }
    if (left + w > window.innerWidth - 8) left = window.innerWidth - w - 8;
    if (left < 8) left = 8;
    if (top < 8) top = 8;
    if (top + h > window.innerHeight - 8) top = Math.max(8, window.innerHeight - h - 8);
    pop.style.left = left + "px";
    pop.style.top = top + "px";
    pop.setAttribute("data-place", place);
    pop.style.setProperty("--arrow-x", Math.min(w - 18, Math.max(18, box.left + box.width / 2 - left)) + "px");
  }

  function bindChartPop(pop, closeBtn, anchor) {
    function close() {
      if (!pop) return;
      pop.hidden = true;
      pop.classList.remove("is-open");
    }
    function open() {
      placeAnchorPop(pop, anchor);
    }
    function toggle() {
      if (!pop || pop.hidden) open();
      else close();
    }
    if (pop && pop.parentNode !== document.body) {
      document.body.appendChild(pop);
    }
    if (closeBtn && !closeBtn.__ftBound) {
      closeBtn.__ftBound = true;
      closeBtn.addEventListener("click", function (event) {
        event.preventDefault();
        event.stopPropagation();
        close();
      });
    }
    if (pop && !pop.__ftBound) {
      pop.__ftBound = true;
      pop.setAttribute("role", "dialog");
      pop.addEventListener("click", function (event) {
        event.stopPropagation();
      });
      document.addEventListener("pointerdown", function (event) {
        if (pop.hidden) return;
        if (pop.contains(event.target)) return;
        if (anchor && anchor.contains(event.target)) return;
        close();
      });
      document.addEventListener("keydown", function (event) {
        if (event.key === "Escape") close();
      });
      window.addEventListener("resize", function () {
        if (!pop.hidden) placeAnchorPop(pop, anchor);
      });
    }
    return { open: open, close: close, toggle: toggle };
  }

  function bindChartOpen(host, openFn) {
    if (!host || host.__ftOpenBound) return;
    host.__ftOpenBound = true;
    host.addEventListener("click", function (event) {
      if (event.target.closest("a, button, .dash-chart-pop")) return;
      openFn();
    });
  }

  function bindSpendPanel(panel) {
    if (!panel || spendUi.bound) return;
    spendUi.bound = true;
    panel.addEventListener("pointerover", function (event) {
      var node = event.target.closest("[data-spend-slice]");
      if (!node) return;
      highlightSpend(Number(node.getAttribute("data-spend-slice")));
    });
    panel.addEventListener("pointerleave", function () {
      highlightSpend(-1);
      var tip = panel.querySelector("[data-spend-tip]");
      if (tip) tip.hidden = true;
    });
    panel.addEventListener("focusin", function (event) {
      var node = event.target.closest("[data-spend-slice]");
      if (node) highlightSpend(Number(node.getAttribute("data-spend-slice")));
    });
    panel.addEventListener("focusout", function () {
      highlightSpend(-1);
    });
  }

  function paintSpendDonut(svg, slices, colors) {
    if (!svg) return;
    svg.innerHTML = "";
    spendUi.circles = [];
    var panel = svg.closest("[data-spend-panel]") || svg.closest(".dash-spend");
    var tip = panel && panel.querySelector("[data-spend-tip]");
    bindSpendPanel(panel);
    var total = slices.reduce(function (sum, item) {
      return sum + Math.max(Number(item.value) || 0, 0);
    }, 0);
    var ns = "http://www.w3.org/2000/svg";
    var radius = 58;
    var circ = 2 * Math.PI * radius;
    appendMetalDefs(svg, SPEND_METALS);
    var track = document.createElementNS(ns, "circle");
    track.setAttribute("cx", "70");
    track.setAttribute("cy", "70");
    track.setAttribute("r", String(radius));
    track.setAttribute("stroke", cssVar("--ft-divider", "#ece9e4"));
    track.setAttribute("stroke-width", "16");
    svg.appendChild(track);

    var offset = 0;
    slices.forEach(function (item, index) {
      var value = Math.max(Number(item.value) || 0, 0);
      if (value <= 0) return;
      var pct = item.percent != null ? Number(item.percent) : (total > 0 ? (value / total) * 100 : 0);
      var len = total > 0 ? (value / total) * circ : 0;
      var color = colors[index % colors.length];
      if (item.swatch) item.swatch.style.background = color;
      var circle = document.createElementNS(ns, "circle");
      var full = len >= circ - 0.05;
      circle.setAttribute("cx", "70");
      circle.setAttribute("cy", "70");
      circle.setAttribute("r", String(radius));
      circle.setAttribute("stroke", metalStroke(SPEND_METALS, index));
      circle.setAttribute("stroke-width", "16");
      circle.setAttribute("stroke-linecap", (!full && len > 8) ? "round" : "butt");
      circle.setAttribute("data-spend-slice", String(index));
      circle.style.cursor = "pointer";
      circle.setAttribute("tabindex", "0");
      circle.setAttribute("role", "img");
      circle.setAttribute(
        "aria-label",
        (item.name || "Category") + " " + balanceMoneyLabel(value) + " " + pct.toFixed(1) + " percent"
      );
      var start = offset;
      if (full) {
        circle.setAttribute("stroke-dasharray", circ.toFixed(2) + " 0");
        circle.setAttribute("stroke-dashoffset", "0");
      } else {
        circle.setAttribute("stroke-dasharray", len.toFixed(2) + " " + circ.toFixed(2));
        circle.setAttribute("stroke-dashoffset", String(-start));
      }
      if (!reduceMotion) {
        circle.style.strokeDashoffset = String(circ);
        requestAnimationFrame(function () {
          circle.style.transition = "stroke-dashoffset 700ms ease-out, stroke-width 180ms ease, opacity 180ms ease";
          circle.style.strokeDashoffset = full ? "0" : String(-start);
        });
      }
      function showTip() {
        highlightSpend(index);
        if (!tip) return;
        tip.innerHTML =
          "<strong>" + escapeHtml(item.name || "Category") + "</strong>" +
          "<span>" + escapeHtml(balanceMoneyLabel(value)) + "</span>" +
          "<em>" + pct.toFixed(1) + "%</em>";
        var box = circle.getBoundingClientRect();
        placeFloatTip(tip, box.left + box.width / 2, box.top);
      }
      function hideTip() {
        if (tip) tip.hidden = true;
      }
      circle.addEventListener("mouseenter", showTip);
      circle.addEventListener("focus", showTip);
      circle.addEventListener("mouseleave", hideTip);
      circle.addEventListener("blur", hideTip);
      circle.addEventListener("keydown", function (event) {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        var open = panel && panel.querySelector("[data-chart-open]");
        if (open) open.click();
      });
      svg.appendChild(circle);
      spendUi.circles.push(circle);
      offset += len;
    });
  }

  function paintDonut(svg, slices, colors) {
    if (!svg) return;
    svg.innerHTML = "";
    var total = slices.reduce(function (sum, item) {
      return sum + Math.max(Number(item.value) || 0, 0);
    }, 0);
    var ns = "http://www.w3.org/2000/svg";
    var track = document.createElementNS(ns, "circle");
    track.setAttribute("cx", "60");
    track.setAttribute("cy", "60");
    track.setAttribute("r", String(R));
    track.setAttribute("stroke", cssVar("--ft-divider", "#ece9e4"));
    track.setAttribute("stroke-width", "14");
    svg.appendChild(track);

    var offset = 0;
    slices.forEach(function (item, index) {
      var value = Math.max(Number(item.value) || 0, 0);
      var len = total > 0 ? (value / total) * C : 0;
      var color = colors[index % colors.length];
      if (item.swatch) item.swatch.style.background = color;
      if (len <= 0) return;
      var circle = document.createElementNS(ns, "circle");
      circle.setAttribute("cx", "60");
      circle.setAttribute("cy", "60");
      circle.setAttribute("r", String(R));
      circle.setAttribute("stroke", color);
      circle.setAttribute("stroke-width", "14");
      circle.setAttribute("stroke-dasharray", len.toFixed(2) + " " + C.toFixed(2));
      circle.setAttribute("stroke-dashoffset", String(-offset));
      circle.style.setProperty("--from", String(C));
      if (!reduceMotion) {
        circle.style.strokeDashoffset = String(C);
        requestAnimationFrame(function () {
          circle.style.transition = "stroke-dashoffset 900ms ease-out";
          circle.style.strokeDashoffset = String(-offset);
        });
      }
      svg.appendChild(circle);
      offset += len;
    });
  }

  function paintBalanceDonut(svg, slices, colors) {
    if (!svg) return;
    svg.innerHTML = "";
    balanceUi.circles = [];
    var host = svg.closest(".dash-balance__donut");
    var panel = svg.closest(".dash-balance");
    var tip = host && host.querySelector("[data-balance-tip]");
    var total = slices.reduce(function (sum, item) {
      return sum + Math.max(Number(item.value) || 0, 0);
    }, 0);
    var ns = "http://www.w3.org/2000/svg";
    var radius = 47;
    var circ = 2 * Math.PI * radius;
    var positive = slices.filter(function (item) { return Math.max(Number(item.value) || 0, 0) > 0; }).length;
    var gap = positive > 1 ? 1.8 : 0;
    appendMetalDefs(svg, ACCOUNT_METALS);
    var track = document.createElementNS(ns, "circle");
    track.setAttribute("cx", "60");
    track.setAttribute("cy", "60");
    track.setAttribute("r", String(radius));
    track.style.stroke = "color-mix(in srgb, var(--ft-divider) 45%, var(--ft-surface))";
    track.setAttribute("stroke-width", "11");
    track.setAttribute("fill", "none");
    svg.appendChild(track);

    var offset = 0;
    slices.forEach(function (item, index) {
      var value = Math.max(Number(item.value) || 0, 0);
      var pct = total > 0 ? (value / total) * 100 : 0;
      var len = total > 0 ? (value / total) * circ : 0;
      var color = colors[index % colors.length];
      if (len <= 0) return;
      var circle = document.createElementNS(ns, "circle");
      var full = len >= circ - 0.05;
      var start = offset;
      var drawn = Math.max(len - gap, 0.6);
      circle.setAttribute("cx", "60");
      circle.setAttribute("cy", "60");
      circle.setAttribute("r", String(radius));
      circle.setAttribute("fill", "none");
      circle.setAttribute("stroke", metalStroke(ACCOUNT_METALS, index));
      circle.setAttribute("stroke-width", "11");
      circle.setAttribute("stroke-linecap", "butt");
      if (full) {
        circle.setAttribute("stroke-dasharray", circ.toFixed(2) + " 0");
        circle.setAttribute("stroke-dashoffset", "0");
      } else {
        circle.setAttribute("stroke-dasharray", drawn.toFixed(2) + " " + circ.toFixed(2));
        circle.setAttribute("stroke-dashoffset", String(-start));
      }
      circle.setAttribute("tabindex", "0");
      circle.setAttribute("role", "img");
      circle.setAttribute(
        "aria-label",
        (item.name || "Account") + " " + balanceMoneyLabel(item.value) + " " + pct.toFixed(1) + " percent"
      );
      circle.style.cursor = "pointer";
      if (!reduceMotion) {
        circle.style.strokeDashoffset = String(circ);
        requestAnimationFrame(function () {
          circle.style.transition = "stroke-dashoffset 800ms ease-out, stroke-width 160ms ease, opacity 180ms ease";
          circle.style.strokeDashoffset = full ? "0" : String(-start);
        });
      }
      function showTip() {
        highlightBalance(index);
        if (!tip) return;
        tip.innerHTML =
          "<strong>" + escapeHtml(item.name || "Account") + "</strong>" +
          "<span>" + escapeHtml(balanceMoneyLabel(item.value)) + "</span>" +
          "<em>" + pct.toFixed(1) + "%</em>";
        var box = circle.getBoundingClientRect();
        placeFloatTip(tip, box.left + box.width / 2, box.top);
      }
      function hideTip() {
        if (tip) tip.hidden = true;
        highlightBalance(-1);
      }
      circle.addEventListener("mouseenter", showTip);
      circle.addEventListener("focus", showTip);
      circle.addEventListener("mouseleave", hideTip);
      circle.addEventListener("blur", hideTip);
      circle.addEventListener("keydown", function (event) {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        if (host) host.click();
      });
      svg.appendChild(circle);
      balanceUi.circles.push(circle);
      offset += len;
    });
    if (host && panel) {
      if (!host.__ftLeaveBound) {
        host.__ftLeaveBound = true;
        host.addEventListener("pointerleave", function () {
          highlightBalance(-1);
          if (tip) tip.hidden = true;
        });
      }
    }
  }

  function sparkValues(trend) {
    var running = 0;
    return trend.map(function (point) {
      running += Number(point.income || point.credit || 0) - Number(point.expense || point.debit || 0);
      return running;
    });
  }

  function sparkPath(points) {
    if (!points.length) return "";
    if (points.length === 1) {
      return "M" + points[0].x.toFixed(1) + " " + points[0].y.toFixed(1);
    }
    var d = "M" + points[0].x.toFixed(1) + " " + points[0].y.toFixed(1);
    for (var i = 0; i < points.length - 1; i++) {
      var p0 = points[Math.max(0, i - 1)];
      var p1 = points[i];
      var p2 = points[i + 1];
      var p3 = points[Math.min(points.length - 1, i + 2)];
      var c1x = p1.x + (p2.x - p0.x) / 6;
      var c1y = p1.y + (p2.y - p0.y) / 6;
      var c2x = p2.x - (p3.x - p1.x) / 6;
      var c2y = p2.y - (p3.y - p1.y) / 6;
      d += " C" + c1x.toFixed(1) + " " + c1y.toFixed(1) + " " + c2x.toFixed(1) + " " + c2y.toFixed(1) + " " + p2.x.toFixed(1) + " " + p2.y.toFixed(1);
    }
    return d;
  }

  function drawSpark(svg, values, color) {
    if (!svg) return;
    var width = svg.clientWidth || 120;
    var height = svg.clientHeight || 32;
    var pad = 4;
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    svg.innerHTML = "";
    if (!values.length) {
      svg.__spark = null;
      return;
    }
    var min = Math.min.apply(null, values);
    var max = Math.max.apply(null, values);
    if (min === max) {
      min -= 1;
      max += 1;
    }
    var innerW = Math.max(width - pad * 2, 1);
    var innerH = Math.max(height - pad * 2, 1);
    var step = values.length > 1 ? innerW / (values.length - 1) : innerW;
    var points = values.map(function (value, index) {
      return {
        x: pad + index * step,
        y: pad + innerH - ((value - min) / (max - min)) * innerH
      };
    });
    var path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", sparkPath(points));
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", color);
    path.setAttribute("stroke-width", "1.8");
    path.setAttribute("stroke-linecap", "round");
    path.setAttribute("stroke-linejoin", "round");
    svg.appendChild(path);
    var last = points[points.length - 1];
    if (last) {
      var dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      dot.setAttribute("cx", last.x.toFixed(1));
      dot.setAttribute("cy", last.y.toFixed(1));
      dot.setAttribute("r", "2.6");
      dot.setAttribute("fill", color);
      svg.appendChild(dot);
    }
    if (!reduceMotion) {
      var total = 0;
      try { total = path.getTotalLength(); } catch (_err) { total = innerW * 2; }
      path.style.strokeDasharray = String(total);
      path.style.strokeDashoffset = String(total);
      requestAnimationFrame(function () {
        path.style.transition = "stroke-dashoffset 700ms ease-out";
        path.style.strokeDashoffset = "0";
      });
    }
    svg.__spark = { values: values, points: points, min: min, max: max };
  }

  function bindSparkTips() {
    root.querySelectorAll("[data-spark]").forEach(function (svg) {
      if (svg._sparkBound) return;
      svg._sparkBound = true;
      var host = svg.closest(".dash-spark-wrap") || svg.closest(".dash-panel");
      var tip = host && host.querySelector("[data-spark-tip]");
      if (!tip) return;
      if (tip.parentNode !== document.body) document.body.appendChild(tip);
      svg.addEventListener("mousemove", function (event) {
        var spark = svg.__spark;
        if (!spark || !spark.points.length) return;
        var rect = svg.getBoundingClientRect();
        var x = event.clientX - rect.left;
        var nearest = 0;
        var best = Infinity;
        spark.points.forEach(function (point, i) {
          var dx = Math.abs(point.x - x);
          if (dx < best) {
            best = dx;
            nearest = i;
          }
        });
        tip.textContent = moneyLabel(spark.values[nearest]);
        placeFloatTip(tip, event.clientX, event.clientY);
      });
      svg.addEventListener("mouseleave", function () {
        tip.hidden = true;
      });
    });
  }

  function drawBars(host, values) {
    if (!host) return;
    host.innerHTML = "";
    var sample = values.slice(-8);
    if (!sample.length) return;
    var max = Math.max.apply(null, sample.concat([1]));
    sample.forEach(function (value) {
      var bar = document.createElement("span");
      bar.style.height = Math.max(4, (Math.abs(value) / max) * 28) + "px";
      host.appendChild(bar);
    });
  }

  function roundRect(ctx, x, y, w, h, r) {
    if (h < 0) {
      y += h;
      h = Math.abs(h);
    }
    var radius = Math.min(r, Math.abs(w) / 2, Math.abs(h) / 2);
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.arcTo(x + w, y, x + w, y + h, radius);
    ctx.arcTo(x + w, y + h, x, y + h, radius);
    ctx.arcTo(x, y + h, x, y, radius);
    ctx.arcTo(x, y, x + w, y, radius);
    ctx.closePath();
  }

  var cashflowWindowState = {
    range: "",
    offset: 0,
    label: "",
    series: null,
    income: 0,
    expense: 0,
    endingBalance: null,
    request: null
  };
  var cashflowState = { series: [], padX: 8, group: 12, progress: 1 };
  var cashflowHover = -1;

  function cashflowMoney(value) {
    if (window.FTFormat) return FTFormat.formatINR(value, { space: true });
    var n = Number(value || 0);
    var body = Math.abs(n).toLocaleString("en-IN", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });
    if (n < 0) return "-₹ " + body;
    return "₹ " + body;
  }

  function cashflowNetMoney(value) {
    var n = Number(value || 0);
    var body = cashflowMoney(Math.abs(n)).replace(/^-/, "");
    if (n < 0) return "-" + body;
    if (n > 0) return "+" + body;
    return body;
  }

  function compactAxis(value) {
    var n = Number(value || 0);
    var sign = n < 0 ? "-" : "";
    var v = Math.abs(n);
    var body;
    if (v >= 10000000) {
      body = (v / 10000000).toFixed(v % 10000000 ? 1 : 0).replace(/\.0$/, "") + "Cr";
    } else if (v >= 100000) {
      body = (v / 100000).toFixed(v % 100000 ? 1 : 0).replace(/\.0$/, "") + "L";
    } else if (v >= 1000) {
      body = (v / 1000).toFixed(v >= 10000 || v % 1000 === 0 ? 0 : 1).replace(/\.0$/, "") + "K";
    } else {
      body = String(Math.round(v));
    }
    return sign + "₹" + body;
  }

  function nicePeak(raw) {
    var value = Math.max(Number(raw) || 0, 0);
    if (value <= 0) return 1;
    var mag = Math.pow(10, Math.floor(Math.log10(value)));
    var n = value / mag;
    var nice = n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10;
    return nice * mag;
  }

  function cashflowPointLabel(point) {
    if (point && point.date && /^\d{4}-\d{2}-\d{2}/.test(String(point.date))) {
      var parts = String(point.date).split("-");
      return Number(parts[2]) + " " + (MONTHS[Number(parts[1]) - 1] || "") + " " + parts[0];
    }
    return (point && (point.date || point.label)) || "";
  }

  function cashflowAxisLabel(point) {
    if (!point) return "";
    if (point.date && /^\d{4}-\d{2}-\d{2}/.test(String(point.date))) {
      var parts = String(point.date).split("-");
      var day = Number(point.day || parts[2] || 0);
      return day ? String(day) : "";
    }
    if (point.day) return String(point.day);
    return point.label || "";
  }

  function drawCashflowFrame(canvas, series, progress) {
    var ctx = canvas.getContext("2d");
    if (!ctx) return;
    var dpr = window.devicePixelRatio || 1;
    var host = canvas.closest(".dash-cashflow__plot") || canvas.parentElement;
    var width = Math.max((host && host.clientWidth) || canvas.clientWidth || 0, 40);
    var height = Math.max((host && host.clientHeight) || canvas.clientHeight || 0, 40);
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    if (!series.length) return;

    var peakPos = 0;
    var totalIncome = 0;
    var totalExpense = 0;
    series.forEach(function (point) {
      var income = Number(point.income || 0);
      var expense = Number(point.expense || 0);
      totalIncome += income;
      totalExpense += expense;
      peakPos = Math.max(peakPos, income, expense);
    });
    peakPos = nicePeak(peakPos);

    var currentBalance = cashflowWindowState.endingBalance != null
      ? Number(cashflowWindowState.endingBalance)
      : Number(root.getAttribute("data-current-balance") || 0);
    var running = currentBalance - totalIncome + totalExpense;
    var balances = series.map(function (point) {
      running += Number(point.income || 0) - Number(point.expense || 0);
      return running;
    });
    var balanceMin = Math.min.apply(Math, balances.concat([currentBalance]));
    var balanceMax = Math.max.apply(Math, balances.concat([currentBalance]));
    if (balanceMax === balanceMin) {
      balanceMax += 1;
      balanceMin -= 1;
    }

    var padL = 40;
    var padR = 8;
    var padT = 10;
    var padB = 22;
    var plotW = Math.max(width - padL - padR, 40);
    var plotH = Math.max(height - padT - padB, 40);
    var sparse = series.length <= 6;
    var minGroup = sparse ? 72 : 0;
    var contentW = sparse
      ? Math.min(plotW, Math.max(series.length * minGroup, 96))
      : plotW;
    var padX = padL + (plotW - contentW) / 2;
    var group = contentW / series.length;
    var bar = Math.max(5, Math.min(sparse ? 22 : 9, group * (sparse ? 0.28 : 0.3)));
    var gap = Math.max(2, Math.min(4, bar * 0.22));
    var pairW = bar * 2 + gap;
    var upH = Math.max(plotH, 24);
    var zeroY = padT + upH;

    function yForBar(value, p) {
      var v = Math.max(Number(value || 0), 0) * (p == null ? progress : p);
      return zeroY - (v / peakPos) * upH;
    }

    function yForBalance(value, p) {
      var ratio = (Number(value || 0) - balanceMin) / (balanceMax - balanceMin);
      var animated = 0.5 + (ratio - 0.5) * (p == null ? progress : p);
      return padT + (1 - animated) * Math.max(plotH * 0.7, 30) + plotH * 0.08;
    }

    cashflowState = {
      series: series,
      padX: padX,
      group: group,
      progress: progress,
      balances: balances
    };

    var grid = cssVar("--ft-grid-line", "rgba(20,25,30,0.06)");
    var ink = cssVar("--ft-faint", "#8a9199");
    var font = cssVar("--ft-font-sans", "sans-serif");
    var incomeColor = cssVar("--ft-positive", "#3f9872");
    var expenseColor = cssVar("--ft-accent", "#b86d3f");
    var netColor = cssVar("--ft-ink", "#1c242c");
    var ticks = [0, peakPos / 2, peakPos];

    ctx.lineWidth = 1;
    ticks.forEach(function (tick) {
      var gy = yForBar(tick, 1);
      ctx.strokeStyle = grid;
      ctx.beginPath();
      ctx.moveTo(padL, gy);
      ctx.lineTo(width - padR, gy);
      ctx.stroke();
      ctx.fillStyle = ink;
      ctx.font = "600 10px " + font;
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      ctx.fillText(compactAxis(tick), padL - 6, gy);
    });

    ctx.strokeStyle = colorMixSafe(netColor, 0.28);
    ctx.beginPath();
    ctx.moveTo(padX, zeroY);
    ctx.lineTo(padX + contentW, zeroY);
    ctx.stroke();

    series.forEach(function (point, i) {
      var active = cashflowHover === i;
      var xMid = padX + i * group + group * 0.5;
      var x0 = xMid - pairW / 2;
      var income = Number(point.income || 0);
      var expense = Number(point.expense || 0);
      var ih = Math.max(income > 0 ? 8 : 0, ((income / peakPos) * upH) * progress);
      var eh = Math.max(expense > 0 ? 8 : 0, ((expense / peakPos) * upH) * progress);
      ctx.globalAlpha = active || cashflowHover < 0 ? 1 : 0.42;
      if (ih > 0) {
        ctx.fillStyle = incomeColor;
        roundRect(ctx, x0, zeroY - ih, bar, ih, 3);
        ctx.fill();
      } else if (sparse) {
        ctx.fillStyle = incomeColor;
        ctx.globalAlpha = 0.22;
        roundRect(ctx, x0, zeroY - 2, bar, 2, 1);
        ctx.fill();
        ctx.globalAlpha = active || cashflowHover < 0 ? 1 : 0.42;
      }
      if (eh > 0) {
        ctx.fillStyle = expenseColor;
        roundRect(ctx, x0 + bar + gap, zeroY - eh, bar, eh, 3);
        ctx.fill();
      } else if (sparse) {
        ctx.fillStyle = expenseColor;
        ctx.globalAlpha = 0.22;
        roundRect(ctx, x0 + bar + gap, zeroY - 2, bar, 2, 1);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
      if (active) {
        ctx.strokeStyle = grid;
        ctx.beginPath();
        ctx.moveTo(xMid, padT);
        ctx.lineTo(xMid, padT + plotH);
        ctx.stroke();
      }
    });

    ctx.beginPath();
    ctx.strokeStyle = netColor;
    ctx.lineWidth = 1.8;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    var started = false;
    balances.forEach(function (value, i) {
      var x = padX + i * group + group * 0.5;
      var y = yForBalance(value);
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    });
    if (started) ctx.stroke();

    if (sparse || series.length <= 12) {
      balances.forEach(function (value, i) {
        ctx.fillStyle = netColor;
        ctx.beginPath();
        ctx.arc(
          padX + i * group + group * 0.5,
          yForBalance(value),
          cashflowHover === i ? 3.2 : 2.3,
          0,
          Math.PI * 2
        );
        ctx.fill();
      });
    }

    ctx.fillStyle = ink;
    ctx.font = "600 10px " + font;
    ctx.textBaseline = "alphabetic";
    var labelEvery = group < 34 ? Math.ceil(36 / Math.max(group, 1)) : 1;
    series.forEach(function (point, i) {
      var label = cashflowAxisLabel(point);
      if (!label) return;
      if (labelEvery > 1 && i !== 0 && i !== series.length - 1 && i % labelEvery !== 0) return;
      ctx.textAlign = "center";
      ctx.fillText(label, padX + i * group + group * 0.5, height - 6);
    });
  }

  function colorMixSafe(color, alpha) {
    if (!color) return "rgba(185,111,61,0.28)";
    if (color.charAt(0) === "#" && (color.length === 7 || color.length === 4)) {
      var hex = color.length === 4
        ? "#" + color[1] + color[1] + color[2] + color[2] + color[3] + color[3]
        : color;
      var r = parseInt(hex.slice(1, 3), 16);
      var g = parseInt(hex.slice(3, 5), 16);
      var b = parseInt(hex.slice(5, 7), 16);
      return "rgba(" + r + "," + g + "," + b + "," + alpha + ")";
    }
    return color;
  }

  function animateCashflow(canvas, series) {
    cashflowHover = -1;
    if (reduceMotion || !series.length) {
      drawCashflowFrame(canvas, series, 1);
      return;
    }
    var start = null;
    function tick(ts) {
      if (!start) start = ts;
      var p = Math.min(1, (ts - start) / 720);
      var eased = 1 - Math.pow(1 - p, 3);
      drawCashflowFrame(canvas, series, eased);
      if (p < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }

  function setMetric(el, value, kind) {
    if (!el) return;
    var n = Number(value || 0);
    el.textContent = kind === "net" ? cashflowNetMoney(n) : cashflowMoney(n);
    el.classList.remove("is-in", "is-out", "is-zero");
    if (kind === "income") el.classList.add("is-in");
    else if (kind === "expense") el.classList.add("is-out");
    else if (n > 0) el.classList.add("is-in");
    else if (n < 0) el.classList.add("is-out");
    else el.classList.add("is-zero");
  }

  function syncCashflowChrome(series) {
    var panel = root.querySelector(".dash-cashflow");
    if (!panel) return;
    var range = cashflowRange();
    var income = 0;
    var expense = 0;
    var hasRemote = cashflowWindowState.series && cashflowWindowState.range === range;
    if (hasRemote) {
      income = Number(cashflowWindowState.income || 0);
      expense = Number(cashflowWindowState.expense || 0);
    } else if (range === "month") {
      income = Number(panel.getAttribute("data-month-income") || 0);
      expense = Number(panel.getAttribute("data-month-expense") || 0);
    } else {
      (series || []).forEach(function (point) {
        income += Number(point.income || 0);
        expense += Number(point.expense || 0);
      });
    }
    setMetric(panel.querySelector("[data-cashflow-income]"), income, "income");
    setMetric(panel.querySelector("[data-cashflow-expense]"), expense, "expense");
    setMetric(panel.querySelector("[data-cashflow-net]"), income - expense, "net");
    var subtitle = panel.querySelector("[data-cashflow-subtitle]");
    if (subtitle) {
      subtitle.textContent = "Income vs Expense · " + (
        hasRemote
          ? cashflowWindowState.label
          : (panel.getAttribute("data-month-label") || "This month")
      );
    }
    var canvas = panel.querySelector("[data-cashflow-chart]");
    if (canvas) {
      canvas.setAttribute(
        "aria-label",
        (hasRemote ? cashflowWindowState.label : (panel.getAttribute("data-month-label") || "This month")) +
        " income " + cashflowMoney(income) +
        ", expense " + cashflowMoney(expense) +
        ", net " + cashflowNetMoney(income - expense)
      );
    }
    var note = panel.querySelector("[data-cashflow-note]");
    if (note) {
      var peakIncome = 0;
      var peakLabel = "";
      (series || []).forEach(function (point) {
        var inc = Number(point.income || 0);
        if (inc > peakIncome) {
          peakIncome = inc;
          peakLabel = cashflowPointLabel(point) || point.label || "";
        }
      });
      if (income > 0 && peakIncome / income >= 0.6 && peakLabel) {
        note.hidden = false;
        note.textContent = "Most income this period posted in " + peakLabel + " (" + cashflowMoney(peakIncome) + ").";
      } else {
        note.hidden = true;
        note.textContent = "";
      }
    }
  }

  function normalizeCashflowWindowSeries(data) {
    var rows = Array.isArray(data && data.series) ? data.series : [];
    if (data && data.granularity === "month") {
      return rows.map(function (point) {
        return {
          income: Number(point.income || 0),
          expense: Number(point.expense || 0),
          label: point.month_short || "",
          date: point.month_label || point.month || ""
        };
      });
    }
    return rows.map(function (point, index) {
      var date = String(point.date || "");
      var parts = date.split("-");
      var day = Number(point.day) || Number(parts[2]) || 0;
      var label = "";
      if (rows.length <= 10 || index === 0 || index === rows.length - 1 || day === 1 || day % 5 === 0) {
        label = day ? String(day) : "";
      }
      return {
        income: Number(point.income || 0),
        expense: Number(point.expense || 0),
        label: label,
        date: date,
        day: day
      };
    });
  }

  function loadCashflowWindow(range, offset, canvas) {
    var panel = root.querySelector(".dash-cashflow");
    if (!panel || !canvas) return;
    var endpoint = panel.getAttribute("data-cashflow-endpoint");
    if (!endpoint) return;

    if (cashflowWindowState.request) cashflowWindowState.request.abort();
    var controller = typeof AbortController === "function" ? new AbortController() : null;
    cashflowWindowState.request = controller;
    panel.classList.add("is-loading");
    var prev = panel.querySelector("[data-cashflow-prev]");
    var next = panel.querySelector("[data-cashflow-next]");
    if (prev) prev.disabled = true;
    if (next) next.disabled = true;

    var url = endpoint + "?range=" + encodeURIComponent(range) + "&offset=" + encodeURIComponent(offset);
    fetch(url, {
      headers: { "Accept": "application/json" },
      signal: controller ? controller.signal : undefined
    })
      .then(function (response) {
        if (!response.ok) throw new Error("Cash flow request failed");
        return response.json();
      })
      .then(function (data) {
        var series = normalizeCashflowWindowSeries(data);
        cashflowWindowState.range = data.range || range;
        cashflowWindowState.offset = Number(data.offset || 0);
        cashflowWindowState.label = data.label || "";
        cashflowWindowState.series = series;
        cashflowWindowState.income = Number(data.income || 0);
        cashflowWindowState.expense = Number(data.expense || 0);
        cashflowWindowState.endingBalance = Number(data.ending_balance || 0);
        syncCashflowChrome(series);
        animateCashflow(canvas, series);
        if (next) next.disabled = !data.can_next;
        if (prev) prev.disabled = cashflowWindowState.offset <= -120;
      })
      .catch(function (error) {
        if (error && error.name === "AbortError") return;
        cashflowWindowState.range = "";
        cashflowWindowState.series = null;
        cashflowWindowState.endingBalance = null;
        var fallback = currentCashflowSeries();
        syncCashflowChrome(fallback);
        drawCashflowFrame(canvas, fallback, 1);
        if (next) next.disabled = offset >= 0;
        if (prev) prev.disabled = false;
      })
      .finally(function () {
        if (cashflowWindowState.request === controller) {
          cashflowWindowState.request = null;
          panel.classList.remove("is-loading");
        }
      });
  }

  function showCashflowTip(canvas, tip, index) {
    var series = cashflowState.series;
    if (!series.length) return;
    var i = Math.max(0, Math.min(series.length - 1, index));
    var point = series[i];
    var balance = Number((cashflowState.balances || [])[i] || 0);
    cashflowHover = i;
    drawCashflowFrame(canvas, series, 1);
    tip.hidden = false;
    tip.innerHTML =
      "<strong>" + escapeHtml(cashflowPointLabel(point) || ("Period " + (i + 1))) + "</strong>" +
      "<div><span>Income</span><em class=\"is-in\">" + escapeHtml(cashflowMoney(point.income)) + "</em></div>" +
      "<div><span>Expense</span><em class=\"is-out\">" + escapeHtml(cashflowMoney(point.expense)) + "</em></div>" +
      "<div><span>Balance</span><em class=\"is-net\">" +
      escapeHtml(cashflowMoney(balance)) + "</em></div>";
  }

  function bindCashflowTooltip(canvas) {
    var tip = root.querySelector("[data-cashflow-tip]");
    if (!tip) return;
    function indexFromX(x) {
      var series = cashflowState.series;
      if (!series.length || !cashflowState.group) return 0;
      return Math.max(0, Math.min(series.length - 1, Math.floor((x - cashflowState.padX) / cashflowState.group)));
    }
    if (tip.parentNode !== document.body) document.body.appendChild(tip);
    canvas.addEventListener("mousemove", function (event) {
      var rect = canvas.getBoundingClientRect();
      var x = event.clientX - rect.left;
      showCashflowTip(canvas, tip, indexFromX(x));
      placeFloatTip(tip, event.clientX, event.clientY);
    });
    canvas.addEventListener("mouseleave", function () {
      tip.hidden = true;
      cashflowHover = -1;
      if (cashflowState.series.length) drawCashflowFrame(canvas, cashflowState.series, 1);
    });
    canvas.addEventListener("keydown", function (event) {
      if (!cashflowState.series.length) return;
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      event.preventDefault();
      var next = cashflowHover < 0 ? 0 : cashflowHover + (event.key === "ArrowRight" ? 1 : -1);
      next = Math.max(0, Math.min(cashflowState.series.length - 1, next));
      var rect = canvas.getBoundingClientRect();
      showCashflowTip(canvas, tip, next);
      placeFloatTip(
        tip,
        rect.left + cashflowState.padX + next * cashflowState.group + 8,
        rect.top + 16
      );
    });
    canvas.addEventListener("blur", function () {
      tip.hidden = true;
      cashflowHover = -1;
      if (cashflowState.series.length) drawCashflowFrame(canvas, cashflowState.series, 1);
    });
  }

  function bindCarousel() {
    var panel = root.querySelector(".dash-cards");
    var carousel = root.querySelector("[data-card-carousel]");
    if (!carousel) return;
    var slides = Array.prototype.slice.call(carousel.querySelectorAll("[data-card-slide]"));
    if (!slides.length) return;
    var dotsHost = root.querySelector("[data-card-dots]");
    var live = document.createElement("span");
    live.className = "visually-hidden";
    live.setAttribute("aria-live", "polite");
    carousel.appendChild(live);
    var index = 0;
    var coarse = window.matchMedia("(hover: none)").matches;
    var dueMonths = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

    function dueLabelFromDate(dt) {
      var day = String(dt.getDate()).padStart(2, "0");
      return day + " " + dueMonths[dt.getMonth()] + " " + dt.getFullYear();
    }

    function dueFromDay(dueDay) {
      var dayNum = Math.max(1, Math.min(31, Number(dueDay) || 5));
      var now = new Date();
      var year = now.getFullYear();
      var month = now.getMonth();
      var last = new Date(year, month + 1, 0).getDate();
      var dt = new Date(year, month, Math.min(dayNum, last));
      var today = new Date(year, month, now.getDate());
      if (dt < today) {
        month += 1;
        if (month > 11) {
          month = 0;
          year += 1;
        }
        last = new Date(year, month + 1, 0).getDate();
        dt = new Date(year, month, Math.min(dayNum, last));
      }
      return dt;
    }

    function fillCardDue(slide) {
      var el = slide.querySelector("[data-card-due]");
      if (!el) return;
      var iso = (slide.getAttribute("data-due-iso") || "").trim();
      if (iso) {
        var parts = iso.split("-");
        if (parts.length >= 3) {
          var parsed = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
          if (!isNaN(parsed.getTime())) {
            el.textContent = dueLabelFromDate(parsed);
            return;
          }
        }
      }
      el.textContent = dueLabelFromDate(dueFromDay(slide.getAttribute("data-due-day")));
    }

    slides.forEach(fillCardDue);

    function show(next) {
      index = (next + slides.length) % slides.length;
      var pair = slides.length === 2;
      var stack = slides.length >= 3;
      carousel.classList.toggle("is-pair", pair);
      carousel.classList.toggle("is-stack", stack);
      slides.forEach(function (slide, i) {
        slide.classList.remove("is-active", "is-prev", "is-next");
        if (i === index) slide.classList.add("is-active");
        else if (stack && i === (index - 1 + slides.length) % slides.length) slide.classList.add("is-prev");
        else if ((stack || pair) && i === (index + 1) % slides.length) slide.classList.add("is-next");
      });
      var leftover = carousel.querySelector("[data-card-ghost]");
      if (leftover) leftover.remove();
      if (dotsHost) {
        if (slides.length > 6) {
          var pager = dotsHost.querySelector("[data-card-count]");
          if (pager) pager.textContent = (index + 1) + " / " + slides.length;
        } else {
          Array.prototype.forEach.call(dotsHost.querySelectorAll("button"), function (dot, i) {
            var on = i === index;
            dot.classList.toggle("is-active", on);
            if (on) dot.setAttribute("aria-current", "true");
            else dot.removeAttribute("aria-current");
          });
        }
      }
      live.textContent = "Showing card " + (index + 1) + " of " + slides.length + ", " + (slides[index].getAttribute("data-name") || "Card");
    }

    if (dotsHost) {
      dotsHost.innerHTML = "";
      if (slides.length > 6) {
        var count = document.createElement("span");
        count.className = "dash-cards__count";
        count.setAttribute("data-card-count", "");
        count.textContent = "1 / " + slides.length;
        dotsHost.appendChild(count);
      } else if (slides.length > 1) {
        slides.forEach(function (_slide, i) {
          var dot = document.createElement("button");
          dot.type = "button";
          dot.setAttribute("aria-label", "Show credit card " + (i + 1));
          dot.addEventListener("click", function () { show(i); });
          dotsHost.appendChild(dot);
        });
      }
    }

    var prev = carousel.querySelector("[data-card-prev]");
    var next = carousel.querySelector("[data-card-next]");
    if (prev) prev.addEventListener("click", function () { show(index - 1); });
    if (next) next.addEventListener("click", function () { show(index + 1); });
    if (slides.length < 2) {
      if (prev) prev.hidden = true;
      if (next) next.hidden = true;
      if (dotsHost) dotsHost.hidden = true;
    }

    slides.forEach(function (slide, i) {
      slide.addEventListener("click", function () {
        if (i !== index) show(i);
      });
      if (!coarse && !reduceMotion) {
        var face = slide.querySelector(".dash-cards__face");
        if (!face) return;
        slide.addEventListener("mousemove", function (event) {
          if (!slide.classList.contains("is-active")) return;
          var rect = face.getBoundingClientRect();
          var px = (event.clientX - rect.left) / Math.max(rect.width, 1) - 0.5;
          var py = (event.clientY - rect.top) / Math.max(rect.height, 1) - 0.5;
          face.style.transform = "rotateX(" + (-py * 5).toFixed(2) + "deg) rotateY(" + (px * 6).toFixed(2) + "deg) scale(1.015)";
        });
        slide.addEventListener("mouseleave", function () {
          face.style.transform = "";
        });
      }
    });

    carousel.tabIndex = 0;
    carousel.setAttribute("aria-label", "Credit card carousel");
    carousel.addEventListener("keydown", function (event) {
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        show(index - 1);
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        show(index + 1);
      }
    });

    var startX = null;
    carousel.addEventListener("touchstart", function (event) {
      startX = event.changedTouches[0].clientX;
    }, { passive: true });
    carousel.addEventListener("touchend", function (event) {
      if (startX == null) return;
      var dx = event.changedTouches[0].clientX - startX;
      if (Math.abs(dx) > 40) show(dx > 0 ? index - 1 : index + 1);
      startX = null;
    });

    show(0);
  }

  function countUp() {
    if (reduceMotion) return;
    root.querySelectorAll("[data-countup]").forEach(function (el) {
      var target = Number(el.getAttribute("data-countup") || 0);
      var prefix = (el.textContent || "").trim().charAt(0) === "₹" ? "₹ " : "";
      var start = null;
      function tick(ts) {
        if (!start) start = ts;
        var p = Math.min(1, (ts - start) / 650);
        var eased = 1 - Math.pow(1 - p, 3);
        var digits = window.FTFormat
          ? FTFormat.formatINRDigits(target * eased)
          : (target * eased).toLocaleString("en-IN", {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2
            });
        el.textContent = prefix + digits;
        if (p < 1) requestAnimationFrame(tick);
      }
      requestAnimationFrame(tick);
    });
  }

  function parseBalanceAccounts() {
    var panel = root.querySelector(".dash-balance");
    if (panel && panel.hasAttribute("data-accounts")) {
      try {
        var data = JSON.parse(panel.getAttribute("data-accounts") || "[]");
        return Array.isArray(data) ? data : [];
      } catch (_err) {
        return [];
      }
    }
    var fallback = parseJson("data-accounts", []);
    return Array.isArray(fallback) ? fallback : [];
  }

  function parseSpendCategories() {
    var panel = root.querySelector("[data-spend-panel]");
    if (panel && panel.hasAttribute("data-categories")) {
      try {
        var data = JSON.parse(panel.getAttribute("data-categories") || "[]");
        return Array.isArray(data) ? data.filter(function (item) {
          return Number(item && item.total) > 0;
        }) : [];
      } catch (_err) {
        return [];
      }
    }
    var fallback = parseJson("data-categories", []);
    return Array.isArray(fallback) ? fallback : [];
  }

  function fillBalanceTable() {
    var panel = root.querySelector(".dash-balance");
    var body = document.querySelector("[data-balance-table]");
    if (!panel || !body) return;
    var rows = [];
    try {
      rows = JSON.parse(panel.getAttribute("data-account-table") || "[]") || [];
    } catch (_err) {
      rows = [];
    }
    if (!Array.isArray(rows) || !rows.length) {
      body.innerHTML = "<p class=\"dash-float-pop__more\">No accounts yet.</p>";
      var emptyInline = panel.querySelector("[data-balance-inline]");
      if (emptyInline) emptyInline.innerHTML = "<p class=\"dash-balance__none\">No accounts yet.</p>";
      return;
    }
    var total = rows.reduce(function (sum, row) {
      var value = Number(row.balance || 0);
      return value > 0 ? sum + value : sum;
    }, 0);
    var inline = panel.querySelector("[data-balance-inline]");
    if (inline) {
      inline.innerHTML = rows.map(function (row, index) {
        var value = Number(row.balance || 0);
        var pct = total > 0 && value > 0 ? (value / total) * 100 : 0;
        var type = ACCOUNT_TYPES[String(row.type || "").toLowerCase()] || "Account";
        var slice = Math.min(index, 4);
        var metal = ACCOUNT_METALS[slice % ACCOUNT_METALS.length];
        var wash = "linear-gradient(135deg," + metal.from + "," + metal.mid + "," + metal.to + ")";
        return (
          "<div class=\"dash-balance-row\" data-balance-row=\"" + slice + "\">" +
            "<i class=\"dash-balance-row__dot\" style=\"background:" + wash + "\"></i>" +
            "<div class=\"dash-balance-row__copy\">" +
              "<strong title=\"" + escapeHtml(row.name || "Account") + "\">" + escapeHtml(row.name || "Account") + "</strong>" +
              "<span>" + escapeHtml(type) + "</span>" +
            "</div>" +
            "<div class=\"dash-balance-row__nums\">" +
              "<b class=\"dash-balance-row__amt" + (value < 0 ? " is-neg" : "") + "\">" +
                escapeHtml(balanceMoneyLabel(value)) +
              "</b>" +
              "<em>" + pct.toFixed(1) + "%</em>" +
            "</div>" +
            "<div class=\"dash-balance-row__bar\" aria-hidden=\"true\">" +
              "<i style=\"width:" + Math.max(0, Math.min(100, pct)) + "%;background:" + wash + "\"></i>" +
            "</div>" +
          "</div>"
        );
      }).join("");
      if (!inline.__ftHoverBound) {
        inline.__ftHoverBound = true;
        inline.addEventListener("pointerover", function (event) {
          var node = event.target.closest("[data-balance-row]");
          if (!node) return;
          var slice = Number(node.getAttribute("data-balance-row"));
          if (slice < balanceUi.circles.length) highlightBalance(slice);
        });
        inline.addEventListener("pointerleave", function () {
          highlightBalance(-1);
        });
      }
    }
    body.innerHTML = rows.map(function (row, index) {
      var value = Number(row.balance || 0);
      var pct = total > 0 && value > 0 ? ((value / total) * 100).toFixed(1) : "0.0";
      var type = ACCOUNT_TYPES[String(row.type || "").toLowerCase()] || "Account";
      var color = ACCOUNT_COLORS[index % ACCOUNT_COLORS.length];
      return (
        "<div class=\"dash-float-row\">" +
          "<span class=\"dash-float-row__name\">" +
            "<i class=\"dash-float-dot\" style=\"background:" + color + "\"></i>" +
            escapeHtml(row.name || "Account") +
          "</span>" +
          "<span class=\"dash-float-row__type\">" + escapeHtml(type) + "</span>" +
          "<span class=\"dash-float-row__amt" + (value < 0 ? " is-neg" : "") + "\">" +
            escapeHtml(balanceMoneyLabel(value)) +
          "</span>" +
          "<span class=\"dash-float-row__pct\">" + pct + "%</span>" +
        "</div>"
      );
    }).join("");
  }

  function fillSpendTable() {
    var panel = root.querySelector("[data-spend-panel]");
    var body = document.querySelector("[data-spend-table]");
    if (!panel || !body) return;
    var rows = parseSpendCategories();
    if (!rows.length) {
      body.innerHTML = "<p class=\"dash-float-pop__more\">No spending recorded yet.</p>";
      return;
    }
    var total = Number(panel.getAttribute("data-spend-total") || 0);
    if (!total) {
      total = rows.reduce(function (sum, row) { return sum + Number(row.total || 0); }, 0);
    }
    var shown = rows.slice(0, 5);
    var extra = rows.length - shown.length;
    body.innerHTML = shown.map(function (row, index) {
      var value = Number(row.total || 0);
      var pct = row.percent != null ? Number(row.percent) : (total > 0 ? (value / total) * 100 : 0);
      var color = SPEND_COLORS[index % SPEND_COLORS.length];
      return (
        "<div class=\"dash-float-cat\">" +
          "<div class=\"dash-float-cat__top\">" +
            "<span class=\"dash-float-cat__name\">" +
              "<i class=\"dash-float-dot\" style=\"background:" + color + "\"></i>" +
              escapeHtml(row.name || "Category") +
            "</span>" +
            "<span class=\"dash-float-cat__meta\">" +
              "<b class=\"dash-float-cat__amt\">" + escapeHtml(balanceMoneyLabel(value)) + "</b>" +
              "<em class=\"dash-float-cat__pct\">" + pct.toFixed(1) + "%</em>" +
            "</span>" +
          "</div>" +
          "<div class=\"dash-float-cat__bar\"><i style=\"width:" + Math.max(0, Math.min(100, pct)) + "%;background:" + color + "\"></i></div>" +
        "</div>"
      );
    }).join("") + (extra > 0 ? "<p class=\"dash-float-pop__more\">+" + extra + " more</p>" : "");
  }

  function bindChartPopups() {
    var balancePanel = root.querySelector(".dash-balance");
    if (balancePanel) {
      var balanceAnchor = balancePanel.querySelector("[data-chart-open]");
      var balancePop = bindChartPop(
        balancePanel.querySelector("[data-balance-dialog]"),
        balancePanel.querySelector("[data-balance-dialog-close]"),
        balanceAnchor
      );
      fillBalanceTable();
      bindChartOpen(balanceAnchor, function () {
        var tip = balancePanel.querySelector("[data-balance-tip]");
        if (tip) tip.hidden = true;
        highlightBalance(-1);
        balancePop.toggle();
      });
    }
    var spendPanel = root.querySelector("[data-spend-panel]");
    if (spendPanel) {
      var spendAnchor = spendPanel.querySelector("[data-chart-open]");
      var spendPop = bindChartPop(
        spendPanel.querySelector("[data-spend-dialog]"),
        spendPanel.querySelector("[data-spend-dialog-close]"),
        spendAnchor
      );
      fillSpendTable();
      bindChartOpen(spendAnchor, function () {
        var tip = spendPanel.querySelector("[data-spend-tip]");
        if (tip) tip.hidden = true;
        highlightSpend(-1);
        spendPop.toggle();
      });
    }
  }

  function renderDonuts() {
    var accountEl = root.querySelector('[data-donut="accounts"]');
    var spendEl = root.querySelector('[data-donut="spend"]');
    var accounts = parseBalanceAccounts();
    var categories = parseSpendCategories();
    paintBalanceDonut(
      accountEl,
      accounts.map(function (item) {
        return {
          value: item.balance || 0,
          name: item.name || "Account"
        };
      }),
      ACCOUNT_COLORS
    );
    paintSpendDonut(
      spendEl,
      categories.map(function (item) {
        return {
          value: item.total || 0,
          name: item.name || "Category",
          percent: item.percent
        };
      }),
      SPEND_COLORS
    );
    bindChartPopups();
  }

  var CAL_SOURCE = { recurring: "Recurring", credit_card: "Credit Card", emi: "EMI" };
  var CAL_MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
  ];
  var CAL_DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  var CAL_ICONS = {
    income: "fa-arrow-trend-up",
    bill: "fa-receipt",
    card: "fa-credit-card",
    emi: "fa-rotate"
  };

  function pad2(value) {
    return String(value).padStart(2, "0");
  }

  function eventDateKey(event, fallback) {
    var raw = event && event.date != null ? String(event.date) : "";
    var key = raw.slice(0, 10);
    if (/^\d{4}-\d{2}-\d{2}$/.test(key)) return key;
    return fallback || "";
  }

  function parseCalJson(value, fallback) {
    try {
      var data = JSON.parse(value || "");
      return data == null ? fallback : data;
    } catch (_err) {
      return fallback;
    }
  }

  function parseCalEvents(button) {
    var data = parseCalJson(button.getAttribute("data-cal-events") || "[]", []);
    return Array.isArray(data) ? data : [];
  }

  function collectCalEvents(panel) {
    var byDate = {};
    var seen = {};

    function add(event, fallbackKey) {
      var key = eventDateKey(event, fallbackKey);
      if (!key) return;
      var stamp = [key, event.label || "", event.amount || 0, event.source || ""].join("|");
      if (seen[stamp]) return;
      seen[stamp] = true;
      var copy = Object.assign({}, event, { date: key });
      (byDate[key] = byDate[key] || []).push(copy);
    }

    var days = parseCalJson(panel.getAttribute("data-cal-days") || "{}", {}) || {};
    Object.keys(days).forEach(function (key) {
      (days[key] || []).forEach(function (event) { add(event, String(key).slice(0, 10)); });
    });
    var upcoming = parseCalJson(panel.getAttribute("data-cal-upcoming") || "[]", []) || [];
    (Array.isArray(upcoming) ? upcoming : []).forEach(function (event) { add(event); });
    return byDate;
  }

  function calKind(event) {
    var source = String((event && event.source) || "").toLowerCase();
    if (source === "credit_card") return "card";
    if (source === "emi") return "emi";
    var amount = Number((event && event.amount) || 0);
    var type = String((event && event.type) || "").toLowerCase();
    if (amount > 0 || type === "credit") return "income";
    var label = String((event && event.label) || "").toLowerCase();
    if (source === "recurring") {
      if (/(electric|water|gas|utility|broadband|internet|phone|mobile)/.test(label)) return "utility";
      if (/(subscription|netflix|spotify|prime|membership|plan)/.test(label)) return "subscription";
      return "utility";
    }
    return "utility";
  }

  function calAmtClass(kind, amount) {
    if (kind === "card") return "is-card";
    return Number(amount || 0) >= 0 ? "is-pos" : "is-neg";
  }

  function calMoney(amount) {
    var value = Number(amount || 0);
    var formatted = window.FTFormat
      ? FTFormat.formatINRDigits(Math.abs(value))
      : Math.abs(value).toLocaleString("en-IN", {
          maximumFractionDigits: 2,
          minimumFractionDigits: 2
        });
    if (value > 0) return "+₹" + formatted;
    if (value < 0) return "−₹" + formatted;
    return "₹" + formatted;
  }

  function calSecondary(event, kind) {
    var source = CAL_SOURCE[event.source] || "";
    var detail =
      kind === "income" ? "Income" :
      kind === "card" ? "Bill Payment" :
      kind === "emi" ? "EMI" :
      kind === "subscription" ? "Subscription" :
      "Utility Bill";
    if (source && detail && source !== detail) return source + " · " + detail;
    return source || detail;
  }

  function calRelative(dateKey, todayKey) {
    if (!dateKey || !todayKey) return "";
    var parts = dateKey.split("-");
    var todayParts = todayKey.split("-");
    if (parts.length < 3 || todayParts.length < 3) return "";
    var a = Date.UTC(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
    var b = Date.UTC(Number(todayParts[0]), Number(todayParts[1]) - 1, Number(todayParts[2]));
    var delta = Math.round((a - b) / 86400000);
    if (delta === 0) return "Today";
    if (delta === 1) return "Tomorrow";
    if (delta > 1) return "In " + delta + " days";
    return "";
  }

  function formatCalLabel(year, month, day) {
    try {
      return new Date(year, month - 1, day).toLocaleDateString("en-IN", {
        day: "2-digit",
        month: "short",
        year: "numeric"
      });
    } catch (_err) {
      return pad2(day) + "/" + pad2(month) + "/" + year;
    }
  }

  function formatCalMonth(year, month) {
    return (CAL_MONTHS[month - 1] || "") + " " + year;
  }

  function formatCalTipDate(year, month, day) {
    return (MONTHS[month - 1] || "") + " " + day;
  }

  function calDotsHtml(events) {
    if (!events.length) return "";
    var kinds = [];
    events.forEach(function (event) {
      var kind = calKind(event);
      if (kinds.indexOf(kind) === -1) kinds.push(kind);
    });
    var shown = kinds.slice(0, 3);
    var extra = events.length > 3 ? events.length - 3 : 0;
    return (
      "<span class=\"dash-mini-cal__dots\">" +
        shown.map(function (kind) {
          return "<i class=\"is-" + kind + "\"></i>";
        }).join("") +
        (extra ? "<b>+" + extra + "</b>" : "") +
      "</span>"
    );
  }

  function calDayUrl(year, month, dayKey) {
    return (
      "/planning/calendar?year=" + encodeURIComponent(year) +
      "&month=" + encodeURIComponent(month) +
      (dayKey ? "&day=" + encodeURIComponent(dayKey) : "")
    );
  }

  function monthEvents(byDate, year, month) {
    var prefix = year + "-" + pad2(month);
    var map = {};
    Object.keys(byDate).forEach(function (key) {
      if (key.slice(0, 7) === prefix) map[key] = byDate[key];
    });
    return map;
  }

  function upcomingMonthEvents(byDate, year, month, todayKey) {
    var prefix = year + "-" + pad2(month);
    var items = [];
    Object.keys(byDate).sort().forEach(function (key) {
      if (key.slice(0, 7) !== prefix) return;
      if (todayKey && key < todayKey) return;
      (byDate[key] || []).forEach(function (event) {
        items.push(event);
      });
    });
    return items.slice(0, 5);
  }

  function renderMiniCalGrid(panel, year, month, daysMap, todayKey, selectedKey) {
    var grid = panel.querySelector("[data-cal-grid]");
    if (!grid) return;
    var first = new Date(year, month - 1, 1);
    var startPad = (first.getDay() + 6) % 7;
    var total = new Date(year, month, 0).getDate();
    var prevLast = new Date(year, month - 1, 0).getDate();
    var cells = startPad + total;
    var trailing = (7 - (cells % 7)) % 7;
    var html = "";
    var i;
    for (i = 0; i < startPad; i += 1) {
      html +=
        "<span class=\"dash-mini-cal__day is-out\"><em>" +
        (prevLast - startPad + i + 1) +
        "</em></span>";
    }
    for (var day = 1; day <= total; day += 1) {
      var key = year + "-" + pad2(month) + "-" + pad2(day);
      var events = daysMap[key] || [];
      var isToday = todayKey && key === todayKey;
      var isSelected = selectedKey && key === selectedKey;
      var label = formatCalLabel(year, month, day);
      html +=
        "<button type=\"button\" class=\"dash-mini-cal__day" +
        (events.length ? " has-pay" : "") +
        (isToday ? " is-today" : "") +
        (isSelected ? " is-selected" : "") +
        "\" data-cal-day=\"" +
        key +
        "\" data-cal-label=\"" +
        escapeHtml(label) +
        "\" data-cal-tip-date=\"" +
        escapeHtml(formatCalTipDate(year, month, day)) +
        "\"" +
        (events.length
          ? " data-cal-events=\"" + escapeHtml(JSON.stringify(events)) + "\""
          : "") +
        " aria-label=\"" +
        escapeHtml(label) +
        (events.length
          ? ", " + events.length + " payment" + (events.length === 1 ? "" : "s")
          : "") +
        "\"><em>" +
        day +
        "</em>" +
        calDotsHtml(events) +
        "</button>";
    }
    for (i = 0; i < trailing; i += 1) {
      html +=
        "<span class=\"dash-mini-cal__day is-out\"><em>" +
        (i + 1) +
        "</em></span>";
    }
    grid.innerHTML = html;
  }

  function renderCalUpcoming(panel, items, todayKey) {
    var list = panel.querySelector("[data-cal-upcoming-list]");
    if (!list) return;
    if (!items.length) {
      list.innerHTML =
        "<div class=\"dash-cal-up__empty\">" +
          "<span class=\"dash-ico\"><i class=\"fa-regular fa-calendar\" aria-hidden=\"true\"></i></span>" +
          "<strong>No upcoming events</strong>" +
          "<p>You're clear for now.</p>" +
        "</div>";
      return;
    }
    list.innerHTML = items.map(function (event) {
      var key = eventDateKey(event);
      var parts = key.split("-");
      var day = Number(parts[2]) || 0;
      var kind = calKind(event);
      var amount = Number(event.amount || 0);
      var relative = calRelative(key, todayKey);
      return (
        "<a class=\"dash-cal-up__row\" href=\"" +
        escapeHtml(calDayUrl(Number(parts[0]), Number(parts[1]), key)) +
        "\">" +
          "<i class=\"dash-cal-up__kind is-" + kind + "\" aria-hidden=\"true\"></i>" +
          "<span class=\"dash-cal-up__meta\">" +
            "<strong class=\"dash-cal-up__name\">" + escapeHtml(event.label || "Payment") + "</strong>" +
            "<small class=\"dash-cal-up__sub\">" + escapeHtml(calSecondary(event, kind)) + "</small>" +
          "</span>" +
          "<span class=\"dash-cal-up__amt " + calAmtClass(kind, amount) + "\">" +
            calMoney(amount) +
            "<em class=\"dash-cal-up__rel\">" + escapeHtml(relative || (day + " " + (MONTHS[Number(parts[1]) - 1] || ""))) + "</em>" +
          "</span>" +
        "</a>"
      );
    }).join("");
  }

  function bindMiniCalendar() {
    var panel = root.querySelector("[data-cal-panel]");
    if (!panel) return;
    var now = new Date();
    var year = Number(panel.getAttribute("data-cal-year")) || now.getFullYear();
    var month = Number(panel.getAttribute("data-cal-month")) || now.getMonth() + 1;
    var todayKey = String(panel.getAttribute("data-cal-today") || "").slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(todayKey)) {
      todayKey = now.getFullYear() + "-" + pad2(now.getMonth() + 1) + "-" + pad2(now.getDate());
    }
    var byDate = collectCalEvents(panel);
    var selectedKey = "";
    var heading = panel.querySelector("[data-cal-heading]");
    var monthLabel = panel.querySelector("[data-cal-month-label]");
    var openLink = panel.querySelector("[data-cal-open]");
    var viewAll = panel.querySelector("[data-cal-viewall]");
    var grid = panel.querySelector("[data-cal-grid]");
    var tip = document.createElement("div");
    tip.className = "dash-cal-tip";
    tip.hidden = true;
    document.body.appendChild(tip);

    function hideTip() {
      tip.classList.remove("is-on");
      window.clearTimeout(tip.__ftHide);
      if (reduceMotion) {
        tip.hidden = true;
        return;
      }
      tip.__ftHide = window.setTimeout(function () { tip.hidden = true; }, 160);
    }

    function showTip(button) {
      var events = parseCalEvents(button);
      if (!events.length) {
        hideTip();
        return;
      }
      window.clearTimeout(tip.__ftHide);
      var shown = events.slice(0, 4);
      var extra = events.length - shown.length;
      tip.innerHTML =
        "<strong>" + escapeHtml(button.getAttribute("data-cal-tip-date") || button.getAttribute("data-cal-label") || "") + "</strong>" +
        "<ul>" +
          shown.map(function (event) {
            var kind = calKind(event);
            var amount = Number(event.amount || 0);
            return (
              "<li><span>" + escapeHtml(event.label || "Payment") + "</span>" +
              "<b class=\"" + calAmtClass(kind, amount) + "\">" + calMoney(amount) + "</b></li>"
            );
          }).join("") +
        "</ul>" +
        (extra > 0 ? "<p class=\"dash-cal-tip__more\">+" + extra + " more</p>" : "");
      var box = button.getBoundingClientRect();
      placeFloatTip(tip, box.left + box.width / 2, box.bottom);
      if (reduceMotion) {
        tip.classList.add("is-on");
      } else {
        requestAnimationFrame(function () { tip.classList.add("is-on"); });
      }
    }

    function syncChrome() {
      var title = formatCalMonth(year, month);
      if (heading) heading.textContent = title;
      if (monthLabel) monthLabel.textContent = title;
      var href = "/planning/calendar?year=" + encodeURIComponent(year) + "&month=" + encodeURIComponent(month);
      if (openLink) openLink.href = href;
      if (viewAll) viewAll.href = href;
    }

    function render() {
      var monthMap = monthEvents(byDate, year, month);
      renderMiniCalGrid(panel, year, month, monthMap, todayKey, selectedKey);
      renderCalUpcoming(panel, upcomingMonthEvents(byDate, year, month, todayKey), todayKey);
      syncChrome();
    }

    function shiftMonth(delta) {
      hideTip();
      var apply = function () {
        month += delta;
        if (month < 1) {
          month = 12;
          year -= 1;
        } else if (month > 12) {
          month = 1;
          year += 1;
        }
        selectedKey = "";
        render();
        if (grid && !reduceMotion) {
          requestAnimationFrame(function () { grid.classList.remove("is-swap"); });
        }
      };
      if (grid && !reduceMotion) {
        grid.classList.add("is-swap");
        window.setTimeout(apply, 160);
      } else {
        apply();
      }
    }

    render();

    panel.addEventListener("click", function (event) {
      var nav = event.target.closest("[data-cal-prev], [data-cal-next]");
      if (nav) {
        event.preventDefault();
        shiftMonth(nav.hasAttribute("data-cal-prev") ? -1 : 1);
        return;
      }
      var day = event.target.closest("[data-cal-day]");
      if (!day || !panel.contains(day)) return;
      event.preventDefault();
      selectedKey = day.getAttribute("data-cal-day") || "";
      panel.querySelectorAll("[data-cal-day]").forEach(function (node) {
        node.classList.toggle("is-selected", node === day);
      });
      window.location.href = calDayUrl(year, month, selectedKey);
    });
    panel.addEventListener("mouseover", function (event) {
      var day = event.target.closest("[data-cal-day]");
      if (day && panel.contains(day)) showTip(day);
    });
    panel.addEventListener("mouseout", function (event) {
      var day = event.target.closest("[data-cal-day]");
      if (!day) return;
      var next = event.relatedTarget;
      if (next && day.contains(next)) return;
      hideTip();
    });
    panel.addEventListener("focusin", function (event) {
      var day = event.target.closest("[data-cal-day]");
      if (day && panel.contains(day)) showTip(day);
    });
    panel.addEventListener("focusout", function (event) {
      var next = event.relatedTarget;
      if (next && panel.contains(next) && next.closest("[data-cal-day]")) return;
      hideTip();
    });
  }

  function bindHealthOrb() {
    var panel = root.querySelector("[data-health-panel]");
    if (!panel) return;
    var orb = panel.querySelector("[data-health-orb]");
    var pop = panel.querySelector("[data-health-pop]");
    var closeBtn = panel.querySelector("[data-health-pop-close]");
    var scoreEl = panel.querySelector("[data-health-count]");
    if (!orb || !pop) return;

    if (pop.parentNode !== document.body) document.body.appendChild(pop);

    var hideTimer = 0;
    var open = false;
    var coarse = window.matchMedia("(hover: none)").matches;

    function animateScore() {
      if (!scoreEl || reduceMotion) return;
      var target = Number(panel.getAttribute("data-health-score"));
      if (!isFinite(target)) return;
      var from = Number(panel.getAttribute("data-health-prev"));
      if (!isFinite(from)) from = 0;
      var start = null;
      function tick(ts) {
        if (!start) start = ts;
        var p = Math.min(1, (ts - start) / 520);
        var eased = 1 - Math.pow(1 - p, 3);
        scoreEl.textContent = String(Math.round(from + (target - from) * eased));
        if (p < 1) requestAnimationFrame(tick);
      }
      requestAnimationFrame(tick);
    }

    function placePop() {
      pop.hidden = false;
      var orbBox = orb.getBoundingClientRect();
      var w = pop.offsetWidth || 300;
      var h = pop.offsetHeight || 220;
      var gap = 14;
      var sheet = window.innerWidth < 768;
      if (sheet) {
        pop.setAttribute("data-place", "sheet");
        pop.style.left = "50%";
        pop.style.top = "auto";
        pop.style.bottom = "12px";
        return;
      }
      pop.style.bottom = "";
      var left = orbBox.left + orbBox.width / 2 - w / 2;
      var top = orbBox.top - h - gap;
      var place = "above";
      if (top < 8) {
        top = orbBox.bottom + gap;
        place = "below";
      }
      if (left < 8) left = 8;
      if (left + w > window.innerWidth - 8) left = Math.max(8, window.innerWidth - w - 8);
      if (top + h > window.innerHeight - 8) top = Math.max(8, window.innerHeight - h - 8);
      pop.style.left = left + "px";
      pop.style.top = top + "px";
      pop.setAttribute("data-place", place);
      pop.style.setProperty("--arrow-x", (orbBox.left + orbBox.width / 2 - left) + "px");
    }

    function showPop() {
      window.clearTimeout(hideTimer);
      placePop();
      orb.classList.add("is-open");
      orb.setAttribute("aria-expanded", "true");
      if (reduceMotion) {
        pop.classList.add("is-on");
      } else {
        requestAnimationFrame(function () { pop.classList.add("is-on"); });
      }
      open = true;
    }

    function hidePop() {
      window.clearTimeout(hideTimer);
      pop.classList.remove("is-on");
      orb.classList.remove("is-open");
      orb.setAttribute("aria-expanded", "false");
      open = false;
      if (reduceMotion) {
        pop.hidden = true;
        return;
      }
      hideTimer = window.setTimeout(function () { pop.hidden = true; }, 160);
    }

    function scheduleHide() {
      window.clearTimeout(hideTimer);
      hideTimer = window.setTimeout(hidePop, 160);
    }

    function togglePop() {
      if (open) hidePop();
      else showPop();
    }

    if (!coarse) {
      orb.addEventListener("mouseenter", showPop);
      orb.addEventListener("mouseleave", scheduleHide);
      pop.addEventListener("mouseenter", function () {
        window.clearTimeout(hideTimer);
        showPop();
      });
      pop.addEventListener("mouseleave", scheduleHide);
    }
    orb.addEventListener("focus", showPop);
    orb.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      if (coarse) togglePop();
      else showPop();
    });
    if (closeBtn) {
      closeBtn.addEventListener("click", function (event) {
        event.preventDefault();
        hidePop();
        orb.focus();
      });
    }
    document.addEventListener("pointerdown", function (event) {
      if (!open) return;
      if (pop.contains(event.target) || orb.contains(event.target)) return;
      hidePop();
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && open) {
        hidePop();
        orb.focus();
      }
    });
    window.addEventListener("resize", function () {
      if (open) placePop();
    });
    animateScore();
  }

  function renderStatic() {
    var trend = parseTrend();
    var nets = sparkValues(trend);
    var sparkSafe = cssVar("--ft-info", "#4f8297");
    var sparkGreen = cssVar("--ft-positive", "#3f9872");
    var sparkCopper = cssVar("--ft-accent", "#b86d3f");
    var sparkAmber = cssVar("--ft-warning", "#a77c35");
    var sparkCoral = cssVar("--ft-negative", "#c94f59");
    var monthly = monthlySeries();
    var savingsSeries = monthly.map(function (point) {
      var income = Number(point.income || 0);
      return income > 0 ? ((income - Number(point.expense || 0)) / income) * 100 : 0;
    });
    var outflowSeries = dailySeries(trend).map(function (point) {
      return Number(point.expense || 0);
    });
    if (!outflowSeries.some(function (value) { return value > 0; })) {
      outflowSeries = monthly.map(function (point) { return Number(point.expense || 0); });
    }
    var healthPanel = root.querySelector("[data-health-panel]");
    var healthSeries = nets.slice();
    if (healthPanel) {
      var prev = Number(healthPanel.getAttribute("data-health-prev"));
      var current = Number(healthPanel.getAttribute("data-health-score"));
      if (!isNaN(prev) && !isNaN(current) && (prev || current)) {
        healthSeries = prev ? [prev, current] : [current];
      }
    }
    root.querySelector('[data-spark="safe"]') &&
      drawSpark(root.querySelector('[data-spark="safe"]'), nets, sparkSafe);
    root.querySelector('[data-spark="net"]') &&
      drawSpark(root.querySelector('[data-spark="net"]'), nets, sparkGreen);
    root.querySelector('[data-spark="balance"]') &&
      drawSpark(root.querySelector('[data-spark="balance"]'), nets, sparkCopper);
    root.querySelector('[data-spark="health"]') &&
      drawSpark(root.querySelector('[data-spark="health"]'), healthSeries, sparkGreen);
    root.querySelector('[data-spark="savings"]') &&
      drawSpark(root.querySelector('[data-spark="savings"]'), savingsSeries.length ? savingsSeries : nets, sparkGreen);
    root.querySelector('[data-spark="outflow"]') &&
      drawSpark(root.querySelector('[data-spark="outflow"]'), outflowSeries.length ? outflowSeries : nets, sparkCoral);
    bindSparkTips();
    renderDonuts();
    renderWeeklyExpenses();
  }

  function renderWeeklyExpenses() {
    var chart = root.querySelector("[data-weekly-chart]");
    if (!chart) return;
    var totals = [0, 0, 0, 0, 0];
    dailySeries(parseTrend()).forEach(function (point) {
      var week = Math.min(4, Math.max(0, Math.floor((Number(point.day || 1) - 1) / 7)));
      totals[week] += Number(point.expense || 0);
    });
    var peak = Math.max.apply(Math, totals);
    chart.querySelectorAll("[data-weekly-bar]").forEach(function (bar, index) {
      var value = totals[index] || 0;
      bar.style.height = peak > 0 ? Math.max(4, (value / peak) * 100) + "%" : "0";
      bar.setAttribute("title", "Week " + (index + 1) + ": " + moneyLabel(value));
    });
    var empty = root.querySelector("[data-weekly-empty]");
    if (empty) empty.hidden = peak > 0;
    var takeaway = root.querySelector("[data-weekly-takeaway]");
    if (takeaway) {
      if (peak <= 0) {
        takeaway.textContent = "No spending recorded this month yet.";
      } else {
        var peakWeek = 0;
        totals.forEach(function (value, index) {
          if (value > totals[peakWeek]) peakWeek = index;
        });
        takeaway.textContent = "Week " + (peakWeek + 1) + " had the highest spend (" + moneyLabel(totals[peakWeek]) + ").";
      }
    }
  }

  var greet = root.querySelector("[data-greeting]");
  if (greet) {
    var hour = new Date().getHours();
    greet.textContent =
      hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : hour < 21 ? "Good evening" : "Good night";
  }

  var canvas = root.querySelector("[data-cashflow-chart]");
  var series = currentCashflowSeries();
  bindCarousel();
  renderStatic();
  syncCashflowChrome(series);
  if (canvas) {
    animateCashflow(canvas, series);
    bindCashflowTooltip(canvas);
    if (typeof ResizeObserver === "function" && !canvas.__ftSizeObs) {
      var plot = canvas.closest(".dash-cashflow__plot") || canvas.parentElement;
      canvas.__ftSizeObs = new ResizeObserver(function () {
        window.clearTimeout(canvas.__ftSizeTimer);
        canvas.__ftSizeTimer = window.setTimeout(function () {
          if (!plot || plot.clientHeight < 40) return;
          drawCashflowFrame(canvas, currentCashflowSeries(), 1);
        }, 40);
      });
      canvas.__ftSizeObs.observe(plot);
    }
  }
  var range = root.querySelector("[data-cashflow-range]");
  if (range && canvas) {
    range.addEventListener("change", function () {
      cashflowWindowState.range = "";
      cashflowWindowState.offset = 0;
      cashflowWindowState.series = null;
      cashflowWindowState.endingBalance = null;
      loadCashflowWindow(range.value, 0, canvas);
    });
  }
  root.querySelectorAll("[data-cashflow-prev], [data-cashflow-next]").forEach(function (button) {
    button.addEventListener("click", function () {
      if (!range) return;
      var direction = button.hasAttribute("data-cashflow-prev") ? -1 : 1;
      var nextOffset = Math.min(0, cashflowWindowState.offset + direction);
      if (nextOffset === cashflowWindowState.offset) return;
      loadCashflowWindow(range.value, nextOffset, canvas);
    });
  });
  if (range && canvas) loadCashflowWindow(range.value, 0, canvas);
  countUp();
  bindMiniCalendar();
  bindHealthOrb();

  window.addEventListener("resize", function () {
    window.clearTimeout(window.__ftDashResize);
    window.__ftDashResize = window.setTimeout(function () {
      renderStatic();
      if (canvas) drawCashflowFrame(canvas, currentCashflowSeries(), 1);
    }, 120);
  });
  window.addEventListener("ft:theme", function () {
    renderStatic();
    if (canvas) drawCashflowFrame(canvas, currentCashflowSeries(), 1);
  });
})();
