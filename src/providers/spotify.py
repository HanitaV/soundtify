import requests

from src.core.accounts import AccountManager

from .base import BaseProvider, LyricLine, Track, format_duration
from .ytmusic import YTMusicProvider

class SpotifyProvider(BaseProvider):
    def __init__(self):
        self.backend = YTMusicProvider()
        self._access_token = ""
        self.last_stream_headers: dict[str, str] = {}

    def _saved_token(self) -> str:
        account = AccountManager().connected_platforms().get("spotify", {})
        if not isinstance(account, dict):
            return ""
        return str(account.get("access_token") or account.get("token") or "")

    def refresh_auth(self) -> None:
        self._access_token = self._saved_token()

    def search(self, query: str) -> list[Track]:
        self.refresh_auth()
        if not self._access_token:
            return self._search_via_ytmusic(query)

        try:
            response = requests.get(
                "https://api.spotify.com/v1/search",
                params={"q": query.strip(), "type": "track", "limit": 10},
                headers={"Authorization": f"Bearer {self._access_token}"},
                timeout=20,
            )
            response.raise_for_status()
            items = response.json().get("tracks", {}).get("items", [])
        except Exception:
            return self._search_via_ytmusic(query)

        tracks = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("name") or "Unknown")
            artists = item.get("artists") or []
            artist = ", ".join(
                str(artist_item.get("name"))
                for artist_item in artists
                if isinstance(artist_item, dict) and artist_item.get("name")
            ) or "Unknown"
            mapped = self.backend.search(f"{artist} {title}")
            if not mapped:
                continue
            track = mapped[0]
            track.title = title
            track.artist = artist
            track.duration = format_duration((item.get("duration_ms") or 0) / 1000)
            track.source = "Spotify (via YT)"
            tracks.append(track)
        return tracks or self._search_via_ytmusic(query)

    def search_suggestions(self, query: str, limit: int = 8) -> list[str]:
        return self.backend.search_suggestions(query, limit)

    def recommendations_for(self, track: Track, limit: int = 20) -> list[Track]:
        tracks = self.backend.recommendations_for(track, limit)
        for item in tracks:
            item.source = "Spotify (via YT)"
        return tracks

    def get_lyrics(self, track_id: str) -> list[LyricLine]:
        return self.backend.get_lyrics(track_id)

    def get_stream_url(self, track_id: str) -> str:
        stream_url = self.backend.get_stream_url(track_id)
        self.last_stream_headers = getattr(self.backend, "last_stream_headers", {})
        return stream_url

    def _search_via_ytmusic(self, query: str) -> list[Track]:
        tracks = self.backend.search(query.strip())
        for track in tracks:
            track.source = "Spotify (via YT)"
        return tracks
