/**
 * Shared browser utilities for MoodJournal.
 *
 * The API address comes from js/config.js, which must be loaded first and is
 * rewritten at deploy time. Nothing here hard-codes an address, so the same
 * file works unchanged against a local backend or API Gateway.
 */

const API_BASE_URL = window.MOODJOURNAL_CONFIG?.API_BASE_URL;

if (!API_BASE_URL) {
  console.error("MoodJournal: js/config.js is missing or did not set API_BASE_URL.");
} else {
  // Open the connection to the API now, while the rest of the page is still
  // parsing, instead of when the first fetch fires. DNS, TCP and the TLS
  // handshake are otherwise all paid serially before the first byte of data is
  // requested - and over a long link that is most of a round trip.
  const preconnect = document.createElement("link");
  preconnect.rel = "preconnect";
  preconnect.href = new URL(API_BASE_URL).origin;
  preconnect.crossOrigin = "";
  document.head.appendChild(preconnect);
}
const TOKEN_STORAGE_KEY = "moodjournal_token";
const TOKEN_EXPIRY_KEY = "moodjournal_token_expiry";
const USER_STORAGE_KEY = "moodjournal_user";

class ApiError extends Error {
  constructor(code, message, status) {
    super(message);
    this.code = code;
    this.status = status;
    this.name = "ApiError";
  }
}

class ApiClient {
  async request(method, path, body = null) {
    const url = API_BASE_URL.replace(/\/$/, "") + path;
    const headers = {};

    if (body !== null) headers["Content-Type"] = "application/json";

    const token = this.getToken();
    if (token) headers.Authorization = `Bearer ${token}`;

    const options = { method, headers };
    if (body !== null) options.body = JSON.stringify(body);

    let response;
    try {
      response = await fetch(url, options);
    } catch (err) {
      throw new ApiError(
        "NETWORK_ERROR",
        "Cannot reach the MoodJournal API. Check your connection and try again.",
        0
      );
    }

    let data = null;
    if (response.status !== 204) {
      const raw = await response.text();
      if (raw) {
        try {
          data = JSON.parse(raw);
        } catch (_err) {
          data = { error: { code: "INVALID_RESPONSE", message: raw } };
        }
      }
    }

    if (!response.ok) {
      const code = data?.error?.code || "UNKNOWN";
      const message = data?.error?.message || `HTTP ${response.status}`;
      if (response.status === 401 && code === "UNAUTHORIZED") {
        clearSession();
      }
      throw new ApiError(code, message, response.status);
    }

    return data;
  }

  get(path) {
    return this.request("GET", path);
  }

  post(path, body) {
    return this.request("POST", path, body);
  }

  put(path, body) {
    return this.request("PUT", path, body);
  }

  delete(path) {
    return this.request("DELETE", path);
  }

  getToken() {
    const token = sessionStorage.getItem(TOKEN_STORAGE_KEY);
    const expiry = sessionStorage.getItem(TOKEN_EXPIRY_KEY);
    if (token && expiry && Date.parse(expiry) <= Date.now()) {
      clearSession();
      return null;
    }
    return token;
  }

  setToken(token, expiresAt = null) {
    if (token) {
      sessionStorage.setItem(TOKEN_STORAGE_KEY, token);
      if (expiresAt) sessionStorage.setItem(TOKEN_EXPIRY_KEY, expiresAt);
    } else {
      sessionStorage.removeItem(TOKEN_STORAGE_KEY);
      sessionStorage.removeItem(TOKEN_EXPIRY_KEY);
    }
  }

  isAuthenticated() {
    return !!this.getToken();
  }
}

function clearSession() {
  sessionStorage.removeItem(TOKEN_STORAGE_KEY);
  sessionStorage.removeItem(TOKEN_EXPIRY_KEY);
  sessionStorage.removeItem(USER_STORAGE_KEY);
}

async function login(username, password) {
  const api = new ApiClient();
  const data = await api.post("/auth/login", { username, password });
  api.setToken(data.token, data.expiresAt);
  sessionStorage.setItem(USER_STORAGE_KEY, JSON.stringify(data.user));
  return data.user;
}

async function register(username, password) {
  const api = new ApiClient();
  const data = await api.post("/auth/register", { username, password });
  api.setToken(data.token, data.expiresAt);
  sessionStorage.setItem(USER_STORAGE_KEY, JSON.stringify(data.user));
  return data.user;
}

function logout() {
  clearSession();
  window.location.href = "login.html";
}

function getCurrentUser() {
  try {
    const stored = sessionStorage.getItem(USER_STORAGE_KEY);
    return stored ? JSON.parse(stored) : null;
  } catch (_err) {
    return null;
  }
}

async function getMe() {
  const api = new ApiClient();
  const data = await api.get("/auth/me");
  sessionStorage.setItem(USER_STORAGE_KEY, JSON.stringify(data.user));
  return data.user;
}

function requireAuth() {
  const api = new ApiClient();
  if (!api.isAuthenticated()) {
    window.location.href = "login.html";
    throw new Error("Not authenticated");
  }
}

async function populateUserSidebar() {
  const render = (user) => {
    const name = document.getElementById("userNameDisplay");
    const detail = document.getElementById("userEmailDisplay");
    if (name) name.textContent = user.username;
    if (detail) detail.textContent = "Signed in";
    return user;
  };

  // The username is saved at sign-in, so the sidebar can render with no
  // network call at all. Fetching it on every page load cost an extra API
  // round trip - through the authorizer Lambda as well - just to redisplay a
  // value already held locally. An invalid token is still caught: the page's
  // own data request returns 401 and clears the session.
  const cached = getCurrentUser();
  if (cached && cached.username) return render(cached);

  try {
    return render(await getMe());
  } catch (err) {
    if (err.status === 401 || err.code === "UNAUTHORIZED") logout();
    throw err;
  }
}

function navigateTo(page) {
  window.location.href = `${page}.html`;
}

function setActivePage(pageName) {
  document.querySelectorAll(".nav-link").forEach((link) => link.classList.remove("active"));
  const activeLink = document.querySelector(`[data-page="${pageName}"]`);
  if (activeLink) activeLink.classList.add("active");
}

function showNotification(message, type = "info", duration = 4000) {
  const existing = document.getElementById("notification");
  if (existing) existing.remove();

  const notification = document.createElement("div");
  notification.id = "notification";
  notification.className = `alert alert-${type} notification-toast`;
  notification.innerHTML = `
    <div style="flex: 1">${escapeHtml(message)}</div>
    <button class="icon-button" aria-label="Close" onclick="this.parentElement.remove()">×</button>
  `;
  document.body.appendChild(notification);
  if (duration > 0) setTimeout(() => notification.remove(), duration);
}

function showSuccess(message, duration = 4000) {
  showNotification(message, "success", duration);
}
function showError(message, duration = 5000) {
  showNotification(message, "danger", duration);
}
function showInfo(message, duration = 4000) {
  showNotification(message, "info", duration);
}

function escapeHtml(value) {
  const text = String(value ?? "");
  const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" };
  return text.replace(/[&<>"']/g, (m) => map[m]);
}

function formatDate(dateStr) {
  if (!dateStr) return "—";
  const date = new Date(`${dateStr}T00:00:00`);
  if (Number.isNaN(date.getTime())) return String(dateStr);
  return date.toLocaleDateString("en-US", {
    weekday: "short",
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function formatDateShort(dateStr) {
  if (!dateStr) return "—";
  const date = new Date(`${dateStr}T00:00:00`);
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function formatDateTime(isoStr) {
  if (!isoStr) return "—";
  const date = new Date(isoStr);
  return date.toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function getRelativeTime(isoStr) {
  const date = new Date(isoStr);
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;
  return formatDate(isoStr.slice(0, 10));
}

function getMoodColor(mood) {
  const colors = {
    POSITIVE: "#10b981",
    NEUTRAL: "#6b7280",
    ANXIOUS: "#f59e0b",
    NEGATIVE: "#ef4444",
  };
  return colors[mood] || colors.NEUTRAL;
}

function renderMoodBadge(mood, confidence = 0, fallback = false) {
  const safeMood = String(mood || "NEUTRAL").toUpperCase();
  const confPercent = Math.round((Number(confidence) || 0) * 100);
  const fallbackTitle = fallback
    ? ' title="Automatic classification was unavailable; saved as Neutral"'
    : "";
  return `
    <span class="mood-badge mood-${safeMood.toLowerCase()}"${fallbackTitle}>
      ${safeMood} · ${confPercent}%${fallback ? " · unclassified" : ""}
    </span>
  `;
}

function debounce(fn, delay = 300) {
  let timeoutId;
  return function (...args) {
    clearTimeout(timeoutId);
    timeoutId = setTimeout(() => fn.apply(this, args), delay);
  };
}

// Markup for a password field with a show/hide toggle. `id` and `autocomplete`
// are passed through to the <input>; the button toggles its type via
// togglePasswordVisibility, which lives next to this so both stay in sync.
function passwordFieldHtml(id, { autocomplete = "", required = true } = {}) {
  return `
    <div class="password-field">
      <input type="password" id="${id}" ${autocomplete ? `autocomplete="${autocomplete}"` : ""} ${required ? "required" : ""} />
      <button type="button" class="password-toggle" aria-label="Show password" onclick="togglePasswordVisibility(this)">
        <svg class="icon-eye" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8Z"></path><circle cx="12" cy="12" r="3"></circle></svg>
        <svg class="icon-eye-off" style="display:none" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a13.16 13.16 0 0 1-3.09 4.24"></path><path d="M6.61 6.61A13.53 13.53 0 0 0 1 12s4 8 11 8a9.26 9.26 0 0 0 5.39-1.61"></path><path d="M2 2l20 20"></path><path d="M14.12 14.12a3 3 0 1 1-4.24-4.24"></path></svg>
      </button>
    </div>
  `;
}

function togglePasswordVisibility(button) {
  const input = button.parentElement.querySelector("input");
  if (!input) return;
  const isPassword = input.type === "password";
  input.type = isPassword ? "text" : "password";
  button.querySelector(".icon-eye").style.display = isPassword ? "none" : "";
  button.querySelector(".icon-eye-off").style.display = isPassword ? "" : "none";
  button.setAttribute("aria-label", isPassword ? "Hide password" : "Show password");
}

function setButtonBusy(button, busy, busyText = "Working...") {
  if (!button) return;
  if (busy) {
    button.dataset.originalText = button.textContent;
    button.textContent = busyText;
    button.disabled = true;
  } else {
    button.textContent = button.dataset.originalText || button.textContent;
    button.disabled = false;
  }
}

function createModal(id, innerHtml) {
  let modal = document.getElementById(id);
  if (!modal) {
    modal = document.createElement("div");
    modal.id = id;
    modal.className = "modal-backdrop";
    modal.innerHTML = `<div class="modal-card"></div>`;
    document.body.appendChild(modal);
    modal.addEventListener("click", (e) => {
      if (e.target === modal) closeModal(id);
    });
  }
  modal.querySelector(".modal-card").innerHTML = innerHtml;
  modal.classList.remove("hidden");
  return modal;
}

function closeModal(id) {
  const modal = document.getElementById(id);
  if (modal) modal.classList.add("hidden");
}

function showChangePasswordModal() {
  const modal = createModal(
    "changePasswordModal",
    `
      <div class="modal-header">
        <div>
          <h2>Change Password</h2>
          <p class="text-sm text-muted">Your new password must contain at least 8 characters, a letter and a number.</p>
        </div>
        <button class="icon-button" type="button" onclick="closeChangePasswordModal()">×</button>
      </div>
      <form id="changePasswordForm">
        <div class="form-group">
          <label for="currentPassword" class="required">Current Password</label>
          ${passwordFieldHtml("currentPassword", { autocomplete: "current-password" })}
        </div>
        <div class="form-group">
          <label for="newPassword" class="required">New Password</label>
          ${passwordFieldHtml("newPassword", { autocomplete: "new-password" })}
        </div>
        <div class="form-group">
          <label for="confirmNewPassword" class="required">Confirm New Password</label>
          ${passwordFieldHtml("confirmNewPassword", { autocomplete: "new-password" })}
        </div>
        <div id="passwordModalError" class="alert alert-danger hidden"></div>
        <div class="modal-actions">
          <button id="changePasswordSubmit" type="submit" class="btn btn-primary">Update Password</button>
          <button type="button" class="btn btn-secondary" onclick="closeChangePasswordModal()">Cancel</button>
        </div>
      </form>
    `
  );

  const form = modal.querySelector("#changePasswordForm");
  form.onsubmit = handleChangePassword;
  modal.querySelector("#currentPassword").focus();
}

function closeChangePasswordModal() {
  closeModal("changePasswordModal");
  const form = document.getElementById("changePasswordForm");
  if (form) form.reset();
}

async function handleChangePassword(e) {
  e.preventDefault();
  const form = e.currentTarget;
  const currentPassword = form.querySelector("#currentPassword").value;
  const newPassword = form.querySelector("#newPassword").value;
  const confirmNewPassword = form.querySelector("#confirmNewPassword").value;
  const errorDiv = form.querySelector("#passwordModalError");
  const submit = form.querySelector("#changePasswordSubmit");

  errorDiv.classList.add("hidden");
  if (newPassword !== confirmNewPassword) {
    errorDiv.textContent = "New passwords do not match.";
    errorDiv.classList.remove("hidden");
    return;
  }

  setButtonBusy(submit, true, "Updating...");
  try {
    const api = new ApiClient();
    await api.post("/auth/change-password", { currentPassword, newPassword });
    closeChangePasswordModal();
    showSuccess("Password updated successfully.");
  } catch (err) {
    errorDiv.textContent = err.message || "Failed to update password.";
    errorDiv.classList.remove("hidden");
    setButtonBusy(submit, false);
  }
}

function installMobileNav() {
  if (!document.querySelector(".sidebar") || document.querySelector(".mobile-topbar")) return;
  const bar = document.createElement("div");
  bar.className = "mobile-topbar";
  bar.innerHTML = `
    <a class="mobile-logo" href="index.html">MoodJournal</a>
    <div class="mobile-links">
      <a href="index.html">Write</a>
      <a href="history.html">History</a>
      <a href="dashboard.html">Dashboard</a>
      <a href="reflection.html">Reflect</a>
      <button type="button" onclick="logout()">Sign out</button>
    </div>`;
  document.body.prepend(bar);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", installMobileNav);
} else {
  installMobileNav();
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    ApiClient,
    ApiError,
    login,
    register,
    logout,
    getCurrentUser,
    getMe,
    requireAuth,
    escapeHtml,
    formatDate,
    formatDateTime,
    getMoodColor,
    renderMoodBadge,
    debounce,
  };
}
