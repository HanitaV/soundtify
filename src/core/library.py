from __future__ import annotations

from src.providers.base import Track
from .security import secure_load_json, secure_save_json


LIBRARY_FILE = "library.json"
MAX_RECENT_TRACKS = 30


class LibraryManager:
    def __init__(self):
        self.data = secure_load_json(LIBRARY_FILE)
        if not isinstance(self.data, dict):
            self.data = {}

        self.data.setdefault("queue", [])
        self.data.setdefault("history", [])
        self.data.setdefault("playlists", {"default": []})
        self.data.setdefault("active_playlist", "default")

    @property
    def queue(self) -> list[Track]:
        return self._tracks_from(self.data.get("queue", []))

    @property
    def history(self) -> list[Track]:
        return self._tracks_from(self.data.get("history", []))

    @property
    def active_playlist_name(self) -> str:
        return str(self.data.get("active_playlist") or "default")

    @property
    def active_playlist(self) -> list[Track]:
        playlists = self.data.setdefault("playlists", {"default": []})
        tracks = playlists.setdefault(self.active_playlist_name, [])
        return self._tracks_from(tracks)

    def _tracks_from(self, items) -> list[Track]:
        if not isinstance(items, list):
            return []
        return [Track.from_dict(item) for item in items if isinstance(item, dict) and item.get("id")]

    def save(self) -> None:
        secure_save_json(LIBRARY_FILE, self.data)

    def add_to_queue(self, track: Track) -> None:
        self.data.setdefault("queue", []).append(track.to_dict())
        self.save()

    def pop_next_queue(self) -> Track | None:
        queue = self.data.setdefault("queue", [])
        if not queue:
            return None
        raw_track = queue.pop(0)
        self.save()
        return Track.from_dict(raw_track)

    def clear_queue(self) -> None:
        self.data["queue"] = []
        self.save()

    def remove_from_queue(self, index: int) -> Track | None:
        queue = self.data.setdefault("queue", [])
        if index < 1 or index > len(queue):
            return None
        raw_track = queue.pop(index - 1)
        self.save()
        return Track.from_dict(raw_track)

    def add_to_history(self, track: Track) -> None:
        history = self.data.setdefault("history", [])
        history.insert(0, track.to_dict())
        self.data["history"] = history[:MAX_RECENT_TRACKS]
        self.save()

    def add_to_playlist(self, track: Track, name: str | None = None) -> str:
        playlist_name = (name or self.active_playlist_name).strip() or "default"
        playlists = self.data.setdefault("playlists", {"default": []})
        playlists.setdefault(playlist_name, []).append(track.to_dict())
        self.data["active_playlist"] = playlist_name
        self.save()
        return playlist_name

    def set_active_playlist(self, name: str) -> None:
        playlist_name = name.strip() or "default"
        self.data.setdefault("playlists", {"default": []}).setdefault(playlist_name, [])
        self.data["active_playlist"] = playlist_name
        self.save()

    def list_playlists(self) -> dict[str, int]:
        playlists = self.data.setdefault("playlists", {"default": []})
        return {str(name): len(items) for name, items in playlists.items() if isinstance(items, list)}

    def remove_from_playlist(self, index: int, name: str | None = None) -> Track | None:
        playlist_name = (name or self.active_playlist_name).strip() or "default"
        playlist = self.data.setdefault("playlists", {"default": []}).setdefault(playlist_name, [])
        if index < 1 or index > len(playlist):
            return None
        raw_track = playlist.pop(index - 1)
        self.save()
        return Track.from_dict(raw_track)
