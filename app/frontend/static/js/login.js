// Login page helpers.

function togglePassword() {
  const input = document.getElementById("password");
  if (!input) return;
  input.type = input.type === "password" ? "text" : "password";
}
