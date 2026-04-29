from __future__ import annotations

import base64
import hashlib
import os
import secrets
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from html import escape
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from .security import secure_load_json, secure_save_json


AUTH_CONFIG_FILE = "auth_config.json"
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8765/callback"
SETUP_URL = "http://127.0.0.1:8766"


@dataclass(frozen=True)
class OAuthProvider:
    name: str
    auth_url: str
    token_url: str
    scopes: tuple[str, ...]
    secret_required: bool = False


PROVIDERS = {
    "spotify": OAuthProvider(
        name="spotify",
        auth_url="https://accounts.spotify.com/authorize",
        token_url="https://accounts.spotify.com/api/token",
        scopes=(
            "user-read-email",
            "playlist-read-private",
            "playlist-modify-private",
            "playlist-modify-public",
        ),
    ),
    "ytmusic": OAuthProvider(
        name="ytmusic",
        auth_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scopes=(
            "https://www.googleapis.com/auth/youtube",
            "https://www.googleapis.com/auth/youtube.readonly",
        ),
    ),
    "soundcloud": OAuthProvider(
        name="soundcloud",
        auth_url="https://secure.soundcloud.com/authorize",
        token_url="https://secure.soundcloud.com/oauth/token",
        scopes=(),
        secret_required=True,
    ),
}


def load_auth_config() -> dict:
    config = secure_load_json(AUTH_CONFIG_FILE)
    if not isinstance(config, dict):
        config = {}
    return config


def save_auth_config(config: dict) -> None:
    secure_save_json(AUTH_CONFIG_FILE, config)


def platform_config(platform: str) -> dict:
    platform_name = platform.strip().lower()
    config = load_auth_config().get(platform_name, {})
    if not isinstance(config, dict):
        config = {}

    prefix = "GOOGLE" if platform_name == "ytmusic" else platform_name.upper()
    return {
        "client_id": os.getenv(f"SOUNDTIFY_{prefix}_CLIENT_ID") or config.get("client_id", ""),
        "client_secret": os.getenv(f"SOUNDTIFY_{prefix}_CLIENT_SECRET") or config.get("client_secret", ""),
        "redirect_uri": os.getenv(f"SOUNDTIFY_{prefix}_REDIRECT_URI")
        or config.get("redirect_uri", DEFAULT_REDIRECT_URI),
    }


def make_code_verifier() -> str:
    return secrets.token_urlsafe(64)


def make_code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def make_state() -> str:
    return secrets.token_urlsafe(24)


def build_authorization(platform: str) -> tuple[str, dict]:
    platform_name = platform.strip().lower()
    provider = PROVIDERS[platform_name]
    config = platform_config(platform_name)
    client_id = str(config.get("client_id") or "").strip()
    client_secret = str(config.get("client_secret") or "").strip()
    redirect_uri = str(config.get("redirect_uri") or DEFAULT_REDIRECT_URI).strip()

    if not client_id:
        raise ValueError(f"Thiếu client_id cho {platform_name}.")
    if provider.secret_required and not client_secret:
        raise ValueError(f"{platform_name} cần client_secret để đổi token.")

    verifier = make_code_verifier()
    state = make_state()
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge_method": "S256",
        "code_challenge": make_code_challenge(verifier),
    }
    if provider.scopes:
        params["scope"] = " ".join(provider.scopes)
    if platform_name == "ytmusic":
        params["access_type"] = "offline"
        params["prompt"] = "consent"

    return f"{provider.auth_url}?{urlencode(params)}", {
        "platform": platform_name,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
        "state": state,
    }


def exchange_code(platform: str, code: str, pending: dict) -> dict:
    platform_name = platform.strip().lower()
    provider = PROVIDERS[platform_name]
    code_value = code.strip()
    if not code_value:
        raise ValueError("Thiếu authorization code.")

    data = {
        "grant_type": "authorization_code",
        "code": code_value,
        "redirect_uri": pending["redirect_uri"],
        "client_id": pending["client_id"],
        "code_verifier": pending["code_verifier"],
    }
    headers = {"Accept": "application/json"}

    if platform_name == "soundcloud":
        secret = pending.get("client_secret", "")
        auth_bytes = f"{pending['client_id']}:{secret}".encode("utf-8")
        headers["Authorization"] = "Basic " + base64.b64encode(auth_bytes).decode("ascii")
    elif pending.get("client_secret"):
        data["client_secret"] = pending["client_secret"]

    response = requests.post(provider.token_url, data=data, headers=headers, timeout=30)
    response.raise_for_status()
    token = response.json()
    if not isinstance(token, dict) or "access_token" not in token:
        raise RuntimeError("Token response không hợp lệ.")
    return token


class OAuthCallbackServer:
    def __init__(self, redirect_uri: str, timeout: int = 180):
        parsed = urlparse(redirect_uri)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("GUI callback chỉ hỗ trợ redirect_uri dạng http://127.0.0.1:<port>/callback.")

        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or 80
        self.path = parsed.path or "/callback"
        self.timeout = timeout
        self.code = ""
        self.state = ""
        self.error = ""
        self._event = threading.Event()
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path != parent.path:
                    self.send_response(404)
                    self.end_headers()
                    return

                params = parse_qs(parsed.query)
                parent.code = (params.get("code") or [""])[0]
                parent.state = (params.get("state") or [""])[0]
                parent.error = (params.get("error") or [""])[0]
                body = (
                    "<html><body style='font-family: sans-serif'>"
                    "<h2>Soundtify login received</h2>"
                    "<p>You can close this browser tab and return to Soundtify.</p>"
                    "</body></html>"
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                parent._event.set()

            def log_message(self, format, *args):
                return

        self._server = HTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def wait(self) -> tuple[str, str]:
        if not self._event.wait(self.timeout):
            raise TimeoutError("Hết thời gian chờ OAuth callback.")
        if self.error:
            raise RuntimeError(f"OAuth provider trả lỗi: {self.error}")
        return self.code, self.state

    def close(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


class OAuthSetupServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 8766):
        self.host = host
        self.port = port
        self.url = f"http://{host}:{port}"
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> str:
        if self._server:
            return self.url

        parent = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                provider = self.provider_from_path()
                self.write_html(parent.render_form(provider))

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0") or 0)
                raw_body = self.rfile.read(length).decode("utf-8", errors="replace")
                form = parse_qs(raw_body)
                provider = (form.get("provider") or [""])[0].strip().lower()
                if provider not in PROVIDERS:
                    self.write_html(parent.render_message("Provider không hợp lệ.", "error"))
                    return

                config = load_auth_config()
                existing = config.get(provider, {})
                if not isinstance(existing, dict):
                    existing = {}

                existing["client_id"] = (form.get("client_id") or [""])[0].strip()
                existing["client_secret"] = (form.get("client_secret") or [""])[0].strip()
                existing["redirect_uri"] = (form.get("redirect_uri") or [DEFAULT_REDIRECT_URI])[0].strip()
                config[provider] = existing
                save_auth_config(config)

                self.write_html(parent.render_message(f"Đã lưu cấu hình {provider}. Quay lại Soundtify và bấm Login / Connect.", "ok"))

            def provider_from_path(self) -> str:
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query)
                provider = (params.get("provider") or ["spotify"])[0].strip().lower()
                return provider if provider in PROVIDERS else "spotify"

            def write_html(self, html: str) -> None:
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                return

        self._server = HTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self.url

    def render_form(self, provider: str) -> str:
        config = platform_config(provider)
        client_id = escape(str(config.get("client_id") or ""))
        client_secret = escape(str(config.get("client_secret") or ""))
        redirect_uri = escape(str(config.get("redirect_uri") or DEFAULT_REDIRECT_URI))
        secret_help = "SoundCloud cần client_secret để đổi token." if provider == "soundcloud" else "Có thể để trống nếu app dùng PKCE public client."
        return f"""<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <title>Soundtify OAuth Setup</title>
  <style>
    body {{ font-family: Segoe UI, Arial, sans-serif; background:#111; color:#f3f3f3; margin:0; padding:32px; }}
    main {{ max-width:760px; margin:auto; }}
    label {{ display:block; margin:18px 0 8px; color:#ddd; }}
    input, select {{ width:100%; box-sizing:border-box; padding:12px; border-radius:6px; border:1px solid #444; background:#1d1d1d; color:#fff; }}
    button {{ margin-top:22px; padding:12px 18px; border:0; border-radius:6px; background:#ff5500; color:white; font-weight:700; cursor:pointer; }}
    .hint {{ color:#aaa; line-height:1.45; }}
    .card {{ background:#1b1b1b; border:1px solid #333; border-radius:8px; padding:22px; }}
    code {{ color:#ff9c66; }}
  </style>
</head>
<body>
  <main>
    <h1>Soundtify Account Setup</h1>
    <p class="hint">Form này ghi vào <code>{AUTH_CONFIG_FILE}</code> trong app data của Soundtify. Không cần nhập biến môi trường thủ công.</p>
    <form class="card" method="post">
      <label>Provider</label>
      <select name="provider">
        {self.provider_option("spotify", provider)}
        {self.provider_option("ytmusic", provider)}
        {self.provider_option("soundcloud", provider)}
      </select>
      <label>Client ID</label>
      <input name="client_id" value="{client_id}" autocomplete="off" required>
      <label>Client Secret</label>
      <input name="client_secret" value="{client_secret}" autocomplete="off">
      <p class="hint">{escape(secret_help)}</p>
      <label>Redirect URI</label>
      <input name="redirect_uri" value="{redirect_uri}" autocomplete="off" required>
      <p class="hint">Nên đăng ký redirect URI này trong dashboard: <code>{DEFAULT_REDIRECT_URI}</code></p>
      <button type="submit">Save config</button>
    </form>
  </main>
</body>
</html>"""

    def provider_option(self, value: str, selected: str) -> str:
        mark = " selected" if value == selected else ""
        return f'<option value="{value}"{mark}>{value}</option>'

    def render_message(self, message: str, kind: str) -> str:
        color = "#5bd979" if kind == "ok" else "#ff6b6b"
        return f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><title>Soundtify OAuth Setup</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;background:#111;color:#f3f3f3;padding:32px}}.box{{max-width:720px;margin:auto;background:#1b1b1b;border:1px solid #333;border-radius:8px;padding:24px}}h1{{color:{color}}}a{{color:#ff9c66}}</style>
</head><body><main class="box"><h1>{escape(message)}</h1><p>Tab này có thể đóng. Quay lại Soundtify để tiếp tục.</p><p><a href="{self.url}">Mở lại setup</a></p></main></body></html>"""

    def close(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
