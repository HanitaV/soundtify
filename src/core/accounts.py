from __future__ import annotations

from datetime import datetime, timezone

from .oauth import build_authorization, exchange_code
from .security import secure_load_json, secure_save_json


ACCOUNTS_FILE = "accounts.json"
SUPPORTED_PLATFORMS = {"ytmusic", "soundcloud", "spotify"}


class AccountManager:
    def __init__(self):
        self.data = secure_load_json(ACCOUNTS_FILE)
        if not isinstance(self.data, dict):
            self.data = {}
        self.data.setdefault("accounts", {})
        self.data.setdefault("oauth_pending", {})
        self.data.setdefault("last_sync", None)

    def save(self) -> None:
        secure_save_json(ACCOUNTS_FILE, self.data)

    def login(self, platform: str, label: str = "", token: str = "") -> None:
        platform_name = platform.strip().lower()
        if platform_name not in SUPPORTED_PLATFORMS:
            raise ValueError(f"Nền tảng không hỗ trợ: {platform}")

        self.data.setdefault("accounts", {})[platform_name] = {
            "label": label.strip() or platform_name,
            "token": token.strip(),
            "connected_at": self._now(),
            "last_sync": None,
        }
        self.save()

    def logout(self, platform: str) -> bool:
        platform_name = platform.strip().lower()
        removed = self.data.setdefault("accounts", {}).pop(platform_name, None)
        self.save()
        return removed is not None

    def connected_platforms(self) -> dict[str, dict]:
        accounts = self.data.setdefault("accounts", {})
        return {name: value for name, value in accounts.items() if isinstance(value, dict)}

    def start_oauth(self, platform: str) -> str:
        platform_name = platform.strip().lower()
        if platform_name not in SUPPORTED_PLATFORMS:
            raise ValueError(f"Nền tảng không hỗ trợ: {platform}")

        url, pending = build_authorization(platform_name)
        self.data.setdefault("oauth_pending", {})[platform_name] = pending
        self.save()
        return url

    def pending_oauth(self, platform: str) -> dict | None:
        pending = self.data.setdefault("oauth_pending", {}).get(platform.strip().lower())
        return pending if isinstance(pending, dict) else None

    def finish_oauth(self, platform: str, code: str) -> dict:
        platform_name = platform.strip().lower()
        pending = self.data.setdefault("oauth_pending", {}).get(platform_name)
        if not isinstance(pending, dict):
            raise ValueError(f"Chưa có phiên OAuth pending cho {platform_name}. Bấm Connect trước.")

        token = exchange_code(platform_name, code, pending)
        self.data.setdefault("accounts", {})[platform_name] = {
            "label": f"{platform_name} OAuth",
            "token_type": token.get("token_type", "Bearer"),
            "access_token": token["access_token"],
            "refresh_token": token.get("refresh_token", ""),
            "expires_in": token.get("expires_in", 0),
            "scope": token.get("scope", ""),
            "connected_at": self._now(),
            "last_sync": None,
        }
        self.data.setdefault("oauth_pending", {}).pop(platform_name, None)
        self.save()
        return self.data["accounts"][platform_name]

    def sync(self, library_snapshot: dict) -> dict:
        now = self._now()
        accounts = self.data.setdefault("accounts", {})
        for account in accounts.values():
            if isinstance(account, dict):
                account["last_sync"] = now

        self.data["last_sync"] = now
        self.data["last_library_snapshot"] = library_snapshot
        self.save()
        return {"synced_accounts": len(accounts), "synced_at": now}

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
