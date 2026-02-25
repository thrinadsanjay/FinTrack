(() => {
  const testBtn = document.querySelector("[data-smtp-test]");
  if (!testBtn) return;

  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";

  function val(name) {
    const el = document.querySelector(`[name="${name}"]`);
    return (el?.value || "").trim();
  }

  function checked(name) {
    const el = document.querySelector(`[name="${name}"]`);
    return Boolean(el?.checked);
  }

  function isValidEmail(email) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(email || "").trim());
  }

  async function runTest() {
    const toEmail = window.prompt("Enter receiver email id for SMTP test:");
    if (toEmail == null) return;
    const receiver = toEmail.trim();
    if (!receiver) {
      if (typeof window.ftNotify === "function") window.ftNotify("Receiver email is required.", "error");
      else window.alert("Receiver email is required.");
      return;
    }
    if (!isValidEmail(receiver)) {
      if (typeof window.ftNotify === "function") window.ftNotify("Please enter a valid receiver email.", "error");
      else window.alert("Please enter a valid receiver email.");
      return;
    }

    const payload = {
      to_email: receiver,
      smtp: {
        enabled: checked("smtp_enabled"),
        host: val("smtp_host"),
        port: val("smtp_port"),
        username: val("smtp_username"),
        password: val("smtp_password"),
        from_email: val("smtp_from_email"),
        tls: checked("smtp_tls"),
      },
    };

    testBtn.disabled = true;
    testBtn.classList.add("is-loading");
    const label = testBtn.textContent;
    testBtn.textContent = "Sending...";
    try {
      const res = await fetch("/admin/settings/smtp/test", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || "Failed to send SMTP test email.");
      }
      if (typeof window.ftNotify === "function") window.ftNotify("Test email sent successfully.", "success");
      else window.alert("Test email sent successfully.");
    } catch (err) {
      if (typeof window.ftNotify === "function") window.ftNotify(err?.message || "SMTP test failed.", "error");
      else window.alert(err?.message || "SMTP test failed.");
    } finally {
      testBtn.classList.remove("is-loading");
      testBtn.disabled = false;
      testBtn.textContent = label || "Test SMTP";
    }
  }

  testBtn.addEventListener("click", runTest);
})();
