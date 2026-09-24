(function (global) {
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var MODE_LABELS = {
    upi: "UPI",
    neft: "NEFT",
    imps: "IMPS",
    rtgs: "RTGS",
    sip: "SIP",
    emi: "EMI",
    netbanking: "Net Banking",
    net_banking: "Net Banking",
    card: "Card",
    cash: "Cash",
    wallet: "Wallet",
    cheque: "Cheque",
    check: "Cheque",
    bank_transfer: "Bank Transfer",
    transfer: "Transfer",
    unknown: "Unknown",
    other: "Other"
  };

  function roundMoney(value) {
    var n = Number(value);
    if (!isFinite(n)) n = 0;
    return Math.round(n * 100) / 100;
  }

  function indianGroup(whole) {
    var digits = String(Math.abs(Math.trunc(whole)));
    if (digits.length <= 3) return digits;
    var last3 = digits.slice(-3);
    var rest = digits.slice(0, -3);
    var parts = [];
    while (rest.length > 2) {
      parts.unshift(rest.slice(-2));
      rest = rest.slice(0, -2);
    }
    if (rest) parts.unshift(rest);
    return parts.join(",") + "," + last3;
  }

  function formatINRDigits(value) {
    var n = roundMoney(value);
    var neg = n < 0;
    n = Math.abs(n);
    var whole = Math.trunc(n);
    var frac = Math.round((n - whole) * 100);
    if (frac >= 100) {
      whole += 1;
      frac = 0;
    }
    var text = indianGroup(whole) + "." + String(frac).padStart(2, "0");
    return neg ? "-" + text : text;
  }

  function formatINR(value, opts) {
    opts = opts || {};
    var digits = formatINRDigits(value);
    var neg = digits.charAt(0) === "-";
    var body = neg ? digits.slice(1) : digits;
    var symbol = opts.symbol === false ? "" : "₹";
    var gap = opts.space ? " " : "";
    var text = symbol + gap + body;
    return neg ? "-" + text : text;
  }

  function formatINRCompact(value) {
    var n = roundMoney(value);
    var sign = n < 0 ? "-" : "";
    n = Math.abs(n);
    if (n >= 10000000) return sign + "₹" + (n / 10000000).toFixed(n >= 100000000 ? 0 : 1).replace(/\.0$/, "") + "Cr";
    if (n >= 100000) return sign + "₹" + (n / 100000).toFixed(n >= 1000000 ? 0 : 1).replace(/\.0$/, "") + "L";
    if (n >= 1000) return sign + "₹" + (n / 1000).toFixed(n >= 10000 ? 0 : 1).replace(/\.0$/, "") + "K";
    return formatINR(value);
  }

  function asDate(value) {
    if (!value) return null;
    if (value instanceof Date && !isNaN(value.getTime())) return value;
    var text = String(value).trim();
    var iso = text.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (iso) return new Date(Number(iso[1]), Number(iso[2]) - 1, Number(iso[3]));
    var dmy = text.match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})$/);
    if (dmy) return new Date(Number(dmy[3]), Number(dmy[2]) - 1, Number(dmy[1]));
    var parsed = new Date(text);
    return isNaN(parsed.getTime()) ? null : parsed;
  }

  function pad2(n) {
    return String(n).padStart(2, "0");
  }

  function formatDateDisplay(value) {
    var d = asDate(value);
    if (!d) return "";
    return pad2(d.getDate()) + " " + MONTHS[d.getMonth()] + " " + d.getFullYear();
  }

  function formatDateInput(value) {
    var d = asDate(value);
    if (!d) return "";
    return pad2(d.getDate()) + "/" + pad2(d.getMonth() + 1) + "/" + d.getFullYear();
  }

  function parseDateInput(value) {
    var text = String(value || "").trim();
    if (!text) return "";
    var iso = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (iso) return text;
    var inDate = text.match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})$/);
    if (!inDate) return "";
    return inDate[3] + "-" + pad2(inDate[2]) + "-" + pad2(inDate[1]);
  }

  function paymentModeLabel(mode) {
    var key = String(mode || "").trim().toLowerCase().replace(/[\s-]+/g, "_");
    return MODE_LABELS[key] || String(mode || "").replace(/_/g, " ");
  }

  function enhanceMoneyNodes(root) {
    (root || document).querySelectorAll(".ft-money").forEach(function (el) {
      if (el.hasAttribute("data-countup")) return;
      var text = (el.textContent || "").trim();
      var match = text.match(/^([++\-−]?)(₹\s*)(-?)([\d,]+)(?:\.(\d{1,2}))?$/);
      if (!match) return;
      var raw = match[4].replace(/,/g, "");
      var n = Number(raw + "." + (match[5] || "00"));
      if (!isFinite(n)) return;
      if (match[1] === "-" || match[1] === "−" || match[3] === "-") n = -Math.abs(n);
      var formatted = formatINR(n, { space: true });
      if (match[1] === "+") formatted = "+" + formatted.replace(/^\+/, "");
      el.textContent = formatted;
    });
  }

  function markDateInputs(root) {
    (root || document).querySelectorAll('input[type="date"]').forEach(function (el) {
      el.setAttribute("lang", "en-IN");
      if (!el.getAttribute("title")) el.setAttribute("title", "Date as DD/MM/YYYY");
      enhanceDateInput(el);
    });
  }

  function enhanceDateInput(native) {
    if (!native || native.dataset.ftDate === "1") return;
    native.dataset.ftDate = "1";
    var wrap = document.createElement("span");
    wrap.className = "ft-date";
    native.parentNode.insertBefore(wrap, native);
    wrap.appendChild(native);
    native.classList.add("ft-date__native");
    native.setAttribute("aria-hidden", "true");
    native.tabIndex = -1;
    var display = document.createElement("input");
    display.type = "text";
    display.className = (native.className || "ft-input").replace("ft-date__native", "") + " ft-date__display";
    display.placeholder = "DD/MM/YYYY";
    display.inputMode = "numeric";
    display.autocomplete = "off";
    display.setAttribute("aria-label", native.getAttribute("aria-label") || "Date as DD/MM/YYYY");
    display.value = native.value ? formatDateInput(native.value) : "";
    wrap.appendChild(display);
    var picker = document.createElement("button");
    picker.type = "button";
    picker.className = "ft-date__picker";
    picker.setAttribute("aria-label", "Open calendar");
    picker.tabIndex = -1;
    picker.innerHTML = '<i class="fa-regular fa-calendar" aria-hidden="true"></i>';
    picker.addEventListener("click", function (event) {
      event.preventDefault();
      if (typeof native.showPicker === "function") {
        try { native.showPicker(); return; } catch (err) { /* fall through */ }
      }
      native.click();
    });
    wrap.appendChild(picker);
    function syncNative() {
      var iso = parseDateInput(display.value);
      if (iso) native.value = iso;
      else if (!display.value.trim()) native.value = "";
    }
    display.addEventListener("change", syncNative);
    display.addEventListener("blur", syncNative);
    native.addEventListener("change", function () {
      display.value = native.value ? formatDateInput(native.value) : "";
    });
    var form = native.form;
    if (form && !form._ftDateBound) {
      form._ftDateBound = true;
      form.addEventListener("submit", function () {
        form.querySelectorAll("input[type='date'][data-ft-date]").forEach(function (input) {
          var shown = input.parentNode && input.parentNode.querySelector(".ft-date__display");
          if (!shown) return;
          var iso = parseDateInput(shown.value);
          if (iso) input.value = iso;
        });
      });
    }
  }

  global.FTFormat = {
    formatINR: formatINR,
    formatINRDigits: formatINRDigits,
    formatINRCompact: formatINRCompact,
    formatDateDisplay: formatDateDisplay,
    formatDateInput: formatDateInput,
    parseDateInput: parseDateInput,
    paymentModeLabel: paymentModeLabel,
    markDateInputs: markDateInputs,
    enhanceMoneyNodes: enhanceMoneyNodes
  };

  function boot() {
    markDateInputs(document);
    enhanceMoneyNodes(document);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})(window);
