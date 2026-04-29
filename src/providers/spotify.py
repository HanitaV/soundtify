from .base import BaseProvider, Track
from .ytmusic import YTMusicProvider

class SpotifyProvider(BaseProvider):
    def __init__(self):
        self.backend = YTMusicProvider()

    def search(self, query: str) -> list[Track]:
        tracks = self.backend.search(query.strip())
        for t in tracks:
            t.source = 'Spotify (via YT)'
        return tracks

    def get_stream_url(self, track_id: str) -> str:
        return self.backend.get_stream_url(track_id)
