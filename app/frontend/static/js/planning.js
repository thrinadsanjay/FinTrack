(function () {
  var root = document.querySelector("[data-planning-page]");
  if (!root) return;

  function cssVar(name, fallback) {
    var value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  }

  function parseAttr(name) {
    try {
      var raw = root.getAttribute(name) || "[]";
      var data = JSON.parse(raw);
      return Array.isArray(data) ? data : [];
    } catch (_err) {
      return [];
    }
  }

  function formatY(value, kind) {
    if (kind === "score") return String(Math.round(value));
    if (window.FTFormat) return FTFormat.formatINRCompact(value);
    return String(Math.round(value));
  }

  function formatX(value) {
    if (!value) return "";
    if (window.FTFormat) return FTFormat.formatDateDisplay(value).replace(/ \d{4}$/, "");
    return String(value).slice(5);
  }

  function drawLine(canvas, points, color, kind) {
    if (!canvas) return;
    var ctx = canvas.getContext("2d");
    if (!ctx) return;
    var values = points.map(function (row) {
      return typeof row === "number" ? row : Number(row.value || 0);
    });
    var labels = points.map(function (row) {
      return typeof row === "number" ? "" : row.label || "";
    });
    var dpr = window.devicePixelRatio || 1;
    var width = canvas.clientWidth || canvas.width || 420;
    var height = canvas.clientHeight || 180;
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, height);
    if (!values.length) values = [0, 0, 0];
    var min = Math.min.apply(null, values.concat(kind === "score" ? [0] : [0]));
    var max = Math.max.apply(null, values.concat(kind === "score" ? [100] : [0]));
    if (kind === "score") {
      min = 0;
      max = 100;
    }
    if (min === max) {
      min -= 1;
      max += 1;
    }
    var padL = 44;
    var padR = 10;
    var padT = 12;
    var padB = 22;
    var step = values.length > 1 ? (width - padL - padR) / (values.length - 1) : 0;
    function yFor(v) {
      return padT + ((max - v) / (max - min)) * (height - padT - padB);
    }
    ctx.strokeStyle = cssVar("--ft-divider", "#282f38");
    ctx.fillStyle = cssVar("--ft-muted", "#7a746c");
    ctx.font = "10px Plus Jakarta Sans, sans-serif";
    ctx.globalAlpha = 0.9;
    for (var i = 0; i <= 4; i++) {
      var gy = padT + ((height - padT - padB) * i) / 4;
      var tick = max - ((max - min) * i) / 4;
      ctx.beginPath();
      ctx.moveTo(padL, gy);
      ctx.lineTo(width - padR, gy);
      ctx.stroke();
      ctx.textAlign = "right";
      ctx.fillText(formatY(tick, kind), padL - 6, gy + 3);
    }
    var mark = [0, Math.floor((values.length - 1) / 2), values.length - 1];
    mark.forEach(function (idx) {
      if (!labels[idx]) return;
      ctx.textAlign = idx === 0 ? "left" : idx === values.length - 1 ? "right" : "center";
      ctx.fillText(formatX(labels[idx]), padL + step * idx, height - 6);
    });
    ctx.globalAlpha = 1;
    ctx.beginPath();
    ctx.strokeStyle = color || cssVar("--ft-accent", "#c47a4a");
    ctx.lineWidth = 1.8;
    ctx.lineJoin = "round";
    values.forEach(function (v, idx) {
      var x = padL + step * idx;
      var y = yFor(v);
      if (idx === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }

  var health = parseAttr("data-health-history").map(function (row) {
    return { value: Number(row.score || 0), label: row.month || row.date || "" };
  });
  if (health.length) {
    drawLine(root.querySelector("[data-health-chart]"), health, cssVar("--ft-accent", "#c47a4a"), "score");
  }

  var forecast = parseAttr("data-forecast-daily").map(function (row) {
    return { value: Number(row.balance || 0), label: row.date || "" };
  });
  if (forecast.length) {
    drawLine(root.querySelector("[data-forecast-chart]"), forecast, cssVar("--ft-info", "#6f9db5"), "money");
  }

  var worth = parseAttr("data-networth-history").map(function (row) {
    return { value: Number(row.net_worth || 0), label: row.month || row.date || "" };
  });
  if (worth.length) {
    drawLine(root.querySelector("[data-networth-chart]"), worth, cssVar("--ft-positive", "#5fa889"), "money");
  }
})();
