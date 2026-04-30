from __future__ import annotations

import os
import re
import threading
from datetime import datetime, timedelta, timezone

import yt_dlp

from src.providers.base import Track

from .accounts import AccountManager
from .security import get_appdata_dir, secure_load_json, secure_save_json


DOWNLOADS_FILE = "downloads.json"
DEFAULT_SETTINGS = {
    "auto_download_played": False,
    "autoplay_suggestions_enabled": True,
    "cleanup_days": 30,
    "cleanup_min_plays": 2,
    "sponsorblock_enabled": False,
}


class DownloadManager:
    def __init__(self):
        self.data = secure_load_json(DOWNLOADS_FILE)
        if not isinstance(self.data, dict):
            self.data = {}
        self.data.setdefault("settings", dict(DEFAULT_SETTINGS))
        self.data.setdefault("tracks", {})
        self.download_dir = os.path.join(get_appdata_dir(), "downloads")
        os.makedirs(self.download_dir, exist_ok=True)
        self._active_downloads: set[str] = set()

    @property
    def settings(self) -> dict:
        settings = self.data.setdefault("settings", dict(DEFAULT_SETTINGS))
        for key, value in DEFAULT_SETTINGS.items():
            settings.setdefault(key, value)
        return settings

    def save(self) -> None:
        secure_save_json(DOWNLOADS_FILE, self.data)

    def track_key(self, track: Track) -> str:
        return f"{track.source}:{track.id}"

    def downloaded_tracks(self) -> dict:
        tracks = self.data.setdefault("tracks", {})
        return tracks if isinstance(tracks, dict) else {}

    def local_path_for(self, track: Track) -> str:
        item = self.downloaded_tracks().get(self.track_key(track), {})
        if not isinstance(item, dict):
            return ""
        path = str(item.get("path") or "")
        return path if path and os.path.exists(path) else ""

    def record_play(self, track: Track) -> dict:
        key = self.track_key(track)
        tracks = self.downloaded_tracks()
        item = tracks.setdefault(key, track.to_dict())
        if not isinstance(item, dict):
            item = track.to_dict()
            tracks[key] = item
        item["play_count"] = int(item.get("play_count") or 0) + 1
        item["last_played"] = self._now()
        self.save()
        return item

    def set_auto_download(self, enabled: bool) -> None:
        self.settings["auto_download_played"] = bool(enabled)
        self.save()

    def set_autoplay_suggestions(self, enabled: bool) -> None:
        self.settings["autoplay_suggestions_enabled"] = bool(enabled)
        self.save()

    def set_cleanup_days(self, days: int) -> None:
        self.settings["cleanup_days"] = max(1, int(days))
        self.save()

    def set_cleanup_min_plays(self, count: int) -> None:
        self.settings["cleanup_min_plays"] = max(0, int(count))
        self.save()

    def set_sponsorblock(self, enabled: bool) -> None:
        self.settings["sponsorblock_enabled"] = bool(enabled)
        self.save()

    def maybe_auto_download(self, track: Track) -> None:
        if not self.settings.get("auto_download_played"):
            return
        self.download_async(track)

    def download_async(self, track: Track) -> None:
        key = self.track_key(track)
        if key in self._active_downloads or self.local_path_for(track):
            return
        self._active_downloads.add(key)

        def worker() -> None:
            try:
                self.download(track)
            finally:
                self._active_downloads.discard(key)

        threading.Thread(target=worker, daemon=True).start()

    def download(self, track: Track) -> str:
        url = self._track_url(track)
        safe_title = self._safe_name(f"{track.artist} - {track.title}")[:120]
        output_template = os.path.join(self.download_dir, f"{safe_title}.%(ext)s")
        opts = {
            "format": "bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "outtmpl": output_template,
        }
        opts.update(self._auth_opts(track))
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            downloaded = ydl.prepare_filename(info)

        if not os.path.exists(downloaded):
            requested = (info or {}).get("requested_downloads") or []
            for item in requested:
                filepath = item.get("filepath")
                if filepath and os.path.exists(filepath):
                    downloaded = filepath
                    break

        key = self.track_key(track)
        item = self.downloaded_tracks().setdefault(key, track.to_dict())
        item.update(
            {
                "path": downloaded,
                "downloaded_at": self._now(),
                "last_played": item.get("last_played") or self._now(),
                "play_count": int(item.get("play_count") or 0),
            }
        )
        self.save()
        return downloaded

    def cleanup(self) -> dict:
        cutoff = datetime.now(timezone.utc) - timedelta(days=int(self.settings["cleanup_days"]))
        min_plays = int(self.settings["cleanup_min_plays"])
        removed = 0
        kept = 0
        tracks = self.downloaded_tracks()
        for key, item in list(tracks.items()):
            if not isinstance(item, dict):
                tracks.pop(key, None)
                continue
            path = str(item.get("path") or "")
            if not path or not os.path.exists(path):
                tracks.pop(key, None)
                continue
            last_played = self._parse_time(str(item.get("last_played") or item.get("downloaded_at") or ""))
            play_count = int(item.get("play_count") or 0)
            if last_played and last_played < cutoff and play_count < min_plays:
                try:
                    os.remove(path)
                except OSError:
                    pass
                tracks.pop(key, None)
                removed += 1
            else:
                kept += 1
        self.save()
        return {"removed": removed, "kept": kept}

    def stats(self) -> dict:
        existing = [
            item for item in self.downloaded_tracks().values()
            if isinstance(item, dict) and os.path.exists(str(item.get("path") or ""))
        ]
        total_bytes = sum(os.path.getsize(str(item.get("path"))) for item in existing)
        return {"count": len(existing), "bytes": total_bytes}

    def _track_url(self, track: Track) -> str:
        source = track.source.lower()
        if "soundcloud" in source and track.id.startswith("http"):
            return track.id
        return f"https://music.youtube.com/watch?v={track.id}"

    def _auth_opts(self, track: Track) -> dict:
        account = AccountManager().connected_platforms()
        source = track.source.lower()
        if "soundcloud" in source:
            soundcloud = account.get("soundcloud", {})
            if isinstance(soundcloud, dict):
                token = str(soundcloud.get("access_token") or soundcloud.get("token") or "")
                if token:
                    return {"username": "oauth", "password": token}
        ytmusic = account.get("ytmusic", {})
        if isinstance(ytmusic, dict):
            cookie = str(ytmusic.get("cookie") or "")
            if cookie:
                return {"http_headers": {"Cookie": cookie}}
        return {}

    def _safe_name(self, name: str) -> str:
        return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .") or "track"

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _parse_time(self, value: str) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
