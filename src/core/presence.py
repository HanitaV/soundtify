from __future__ import annotations

import os
import time

from src.providers.base import Track, format_duration

from . import debug_log
from .security import secure_load_json


PRESENCE_CONFIG_FILE = "presence_config.json"
DEFAULT_DISCORD_CLIENT_ID = "1499277199012925482"


class PresenceManager:
    def __init__(self):
        self.discord_client_id = self._discord_client_id()
        self.discord_rpc = None
        self.discord_available = True
        self.discord_connected = False
        self.windows_player = None
        self.windows_controls = None
        self.windows_available = True

    def set_track(
        self,
        track: Track,
        provider_name: str,
        elapsed_seconds: int = 0,
        duration_seconds: int = 0,
        url: str = "",
        playing: bool = True,
    ) -> None:
        self._update_discord(track, provider_name, elapsed_seconds, duration_seconds, url, playing)
        self._update_windows(track, provider_name, playing)

    def set_paused(self, track: Track | None, elapsed_seconds: int = 0) -> None:
        if not track:
            self.clear()
            return
        self._update_discord(track, track.source, elapsed_seconds, 0, "", False)
        self._update_windows(track, track.source, False)

    def clear(self) -> None:
        if self.discord_rpc and self.discord_connected:
            try:
                self.discord_rpc.clear()
            except Exception as exc:
                debug_log.warning("Discord RPC clear failed", error=str(exc))
        if self.windows_controls:
            try:
                status = self._windows_playback_status("CLOSED")
                if status is not None:
                    self.windows_controls.playback_status = status
            except Exception as exc:
                debug_log.warning("Windows presence clear failed", error=str(exc))

    def close(self) -> None:
        self.clear()
        if self.discord_rpc and self.discord_connected:
            try:
                self.discord_rpc.close()
            except Exception as exc:
                debug_log.warning("Discord RPC close failed", error=str(exc))
        self.discord_connected = False

    def _discord_client_id(self) -> str:
        env_value = os.environ.get("SOUNDTIFY_DISCORD_CLIENT_ID", "").strip()
        if env_value:
            return env_value
        config = secure_load_json(PRESENCE_CONFIG_FILE)
        if isinstance(config, dict):
            configured = str(config.get("discord_client_id") or "").strip()
            if configured:
                return configured
        return DEFAULT_DISCORD_CLIENT_ID

    def _connect_discord(self) -> bool:
        if self.discord_connected:
            return True
        if not self.discord_available or not self.discord_client_id:
            return False
        try:
            from pypresence import Presence

            self.discord_rpc = Presence(self.discord_client_id)
            self.discord_rpc.connect()
            self.discord_connected = True
            debug_log.info("Discord RPC connected")
            return True
        except Exception as exc:
            self.discord_available = False
            debug_log.warning("Discord RPC unavailable", error=str(exc))
            return False

    def _update_discord(
        self,
        track: Track,
        provider_name: str,
        elapsed_seconds: int,
        duration_seconds: int,
        url: str,
        playing: bool,
    ) -> None:
        if not self._connect_discord():
            return

        payload = {
            "details": self._clip(track.title, 128),
            "state": self._clip(f"{track.artist} - {provider_name}", 128),
            "large_text": "Soundtify",
        }
        if playing:
            start = int(time.time()) - max(0, int(elapsed_seconds or 0))
            payload["start"] = start
            if duration_seconds and duration_seconds > elapsed_seconds:
                payload["end"] = start + int(duration_seconds)
        else:
            payload["state"] = self._clip(f"Paused at {format_duration(elapsed_seconds)} - {track.artist}", 128)
        if url.startswith(("http://", "https://")):
            payload["buttons"] = [{"label": "Open track", "url": url}]

        try:
            self.discord_rpc.update(**payload)
        except Exception as exc:
            self.discord_connected = False
            self.discord_available = False
            debug_log.warning("Discord RPC update failed", error=str(exc))

    def _ensure_windows(self) -> bool:
        if self.windows_controls:
            return True
        if not self.windows_available or os.name != "nt":
            return False
        try:
            MediaPlayer = self._windows_media_player_class()

            self.windows_player = MediaPlayer()
            self.windows_controls = self.windows_player.system_media_transport_controls
            self.windows_controls.is_enabled = True
            self.windows_controls.is_play_enabled = True
            self.windows_controls.is_pause_enabled = True
            self.windows_controls.is_stop_enabled = True
            debug_log.info("Windows media presence enabled")
            return True
        except Exception as exc:
            self.windows_available = False
            debug_log.warning("Windows media presence unavailable", error=str(exc))
            return False

    def _update_windows(self, track: Track, provider_name: str, playing: bool) -> None:
        if not self._ensure_windows():
            return
        try:
            MediaPlaybackType = self._windows_media_playback_type_class()

            updater = self.windows_controls.display_updater
            updater.type = MediaPlaybackType.MUSIC
            props = updater.music_properties
            props.title = track.title
            props.artist = track.artist
            props.album_artist = provider_name
            updater.update()
            status = self._windows_playback_status("PLAYING" if playing else "PAUSED")
            if status is not None:
                self.windows_controls.playback_status = status
        except Exception as exc:
            self.windows_available = False
            debug_log.warning("Windows media presence update failed", error=str(exc))

    def _windows_playback_status(self, name: str):
        try:
            MediaPlaybackStatus = self._windows_media_playback_status_class()
            return getattr(MediaPlaybackStatus, name)
        except Exception:
            return None

    def _windows_media_player_class(self):
        try:
            from winrt.windows.media.playback import MediaPlayer

            return MediaPlayer
        except Exception:
            from winsdk.windows.media.playback import MediaPlayer

            return MediaPlayer

    def _windows_media_playback_type_class(self):
        try:
            from winrt.windows.media import MediaPlaybackType

            return MediaPlaybackType
        except Exception:
            from winsdk.windows.media import MediaPlaybackType

            return MediaPlaybackType

    def _windows_media_playback_status_class(self):
        try:
            from winrt.windows.media import MediaPlaybackStatus

            return MediaPlaybackStatus
        except Exception:
            from winsdk.windows.media import MediaPlaybackStatus

            return MediaPlaybackStatus

    def _clip(self, text: str, limit: int) -> str:
        value = str(text or "")
        return value if len(value) <= limit else value[: limit - 1] + "..."
