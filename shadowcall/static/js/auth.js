import { api } from "/static/js/api.js";

const mode = document.body.dataset.mode;
const form = document.querySelector("[data-form]");
const errBox = document.querySelector("[data-error]");
const errText = document.querySelector("[data-error-text]");
const submit = document.querySelector("[data-submit]");
const label = submit.textContent;

const reveal = document.querySelector("[data-reveal]");
reveal?.addEventListener("click", () => {
  const input = document.getElementById("password");
  const show = input.type === "password";
  input.type = show ? "text" : "password";
  reveal.setAttribute("aria-pressed", String(show));
  reveal.setAttribute("aria-label", show ? "Hide password" : "Show password");
  reveal.querySelector("use").setAttribute("href", `/static/icons.svg#i-${show ? "eye-off" : "eye"}`);
});

function fail(msg, field) {
  errText.textContent = msg;
  errBox.hidden = false;
  form.querySelectorAll("[aria-invalid]").forEach((el) => el.removeAttribute("aria-invalid"));
  if (field) { const el = document.getElementById(field); el?.setAttribute("aria-invalid", "true"); el?.focus(); }
}

function nextUrl() {
  const n = new URLSearchParams(location.search).get("next") || "/app";
  return n.startsWith("/") && !n.startsWith("//") ? n : "/app"; // never redirect off-site
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  errBox.hidden = true;
  const data = Object.fromEntries(new FormData(form));
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(data.email || "")) return fail("Enter a valid email address.", "email");
  if (mode === "signup" && (data.password || "").length < 10) return fail("Use at least 10 characters for the password.", "password");
  if (!data.password) return fail("Enter your password.", "password");
  submit.disabled = true;
  submit.innerHTML = `<svg class="icon spin" aria-hidden="true"><use href="/static/icons.svg#i-loader-circle"/></svg>${mode === "signup" ? "Creating account…" : "Signing in…"}`;
  try {
    await api(mode === "signup" ? "/api/auth/signup" : "/api/auth/login", { method: "POST", body: data });
    location.href = nextUrl();
  } catch (err) {
    fail(err.message, err.status === 409 || err.status === 400 ? (/password/i.test(err.message) ? "password" : "email") : null);
    submit.disabled = false;
    submit.textContent = label;
  }
});

api("/api/auth/me").then((me) => {
  if (!me.auth || me.user) location.href = nextUrl();
  if (mode === "signup" && !me.signup) fail("Sign-up is closed on this server. Ask the owner for an account.");
}).catch(() => {});
