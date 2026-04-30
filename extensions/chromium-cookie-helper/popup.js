const COOKIE_URLS = [
  "https://music.youtube.com/",
  "https://www.youtube.com/",
  "https://youtube.com/",
  "https://accounts.google.com/"
];

const REQUIRED_NAMES = ["__Secure-3PAPISID", "SAPISID", "__Secure-1PAPISID"];

const statusEl = document.getElementById("status");
const requiredStateEl = document.getElementById("requiredState");
const cookieCountEl = document.getElementById("cookieCount");

document.getElementById("copyCookie").addEventListener("click", copyCookieHeader);
document.getElementById("copySapisid").addEventListener("click", copySapisidOnly);
document.getElementById("openYtmusic").addEventListener("click", () => {
  chrome.tabs.create({ url: "https://music.youtube.com/" });
});

refreshState();

async function refreshState() {
  try {
    const cookies = await getRelevantCookies();
    const required = findRequiredCookie(cookies);
    cookieCountEl.textContent = String(cookies.length);
    requiredStateEl.textContent = required ? "Found" : "Missing";
    setStatus(
      required
        ? "Cookie is available. You can copy it into Soundtify."
        : "Login to YouTube Music first, then reopen this popup.",
      required ? "ok" : ""
    );
  } catch (error) {
    setStatus(error.message || String(error), "error");
  }
}

async function copyCookieHeader() {
  try {
    const cookies = await getRelevantCookies();
    const required = findRequiredCookie(cookies);
    if (!required) {
      throw new Error("Missing SAPISID / __Secure-3PAPISID. Login to YouTube Music first.");
    }
    const cookieHeader = buildCookieHeader(cookies);
    await navigator.clipboard.writeText(`Cookie: ${cookieHeader}`);
    setStatus("Copied Cookie header. Paste it into Soundtify Search, then choose Paste cookie from Search.", "ok");
  } catch (error) {
    setStatus(error.message || String(error), "error");
  }
}

async function copySapisidOnly() {
  try {
    const cookies = await getRelevantCookies();
    const required = findRequiredCookie(cookies);
    if (!required) {
      throw new Error("Missing SAPISID / __Secure-3PAPISID.");
    }
    await navigator.clipboard.writeText(`${required.name}=${required.value}`);
    setStatus(`Copied ${required.name}. Paste it into Soundtify Search if you only need the required cookie.`, "ok");
  } catch (error) {
    setStatus(error.message || String(error), "error");
  }
}

async function getRelevantCookies() {
  const byName = new Map();
  for (const url of COOKIE_URLS) {
    const cookies = await chrome.cookies.getAll({ url });
    for (const cookie of cookies) {
      if (!cookie.name || !cookie.value) continue;
      if (!isRelevantCookie(cookie)) continue;
      if (!byName.has(cookie.name)) {
        byName.set(cookie.name, cookie);
      }
    }
  }
  return [...byName.values()].sort((a, b) => a.name.localeCompare(b.name));
}

function isRelevantCookie(cookie) {
  const name = cookie.name || "";
  if (REQUIRED_NAMES.includes(name)) return true;
  if (name === "SID" || name === "__Secure-1PSID" || name === "__Secure-3PSID") return true;
  if (name.startsWith("__Secure-") || name.startsWith("LOGIN_")) return true;
  return name === "HSID" || name === "SSID" || name === "APISID";
}

function findRequiredCookie(cookies) {
  for (const name of REQUIRED_NAMES) {
    const cookie = cookies.find((item) => item.name === name);
    if (cookie) return cookie;
  }
  return null;
}

function buildCookieHeader(cookies) {
  return cookies
    .map((cookie) => `${cookie.name}=${cookie.value}`)
    .join("; ");
}

function setStatus(message, kind = "") {
  statusEl.textContent = message;
  statusEl.className = `status ${kind}`.trim();
}
