from ytmusicapi import YTMusic
import yt_dlp
from .base import BaseProvider, Track, extract_stream_url

class YTMusicProvider(BaseProvider):
    def __init__(self):
        self.ytmusic = YTMusic()
        self.ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'noplaylist': True,
        }

    def search(self, query: str) -> list[Track]:
        results = self.ytmusic.search(query.strip(), filter='songs', limit=10)
        tracks = []
        for res in results:
            artist_names = [
                artist.get('name')
                for artist in res.get('artists', [])
                if isinstance(artist, dict) and artist.get('name')
            ]
            artist = ", ".join(artist_names) or "Unknown"
            duration = res.get('duration', '0:00')
            video_id = res.get('videoId')
            if not video_id:
                continue
            tracks.append(Track(
                id=str(video_id),
                title=res.get('title', 'Unknown'),
                artist=artist,
                duration=duration,
                source='YTMusic'
            ))
            if len(tracks) >= 10:
                break
        return tracks

    def get_stream_url(self, track_id: str) -> str:
        url = f"https://music.youtube.com/watch?v={track_id}"
        with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            stream_url = extract_stream_url(info)
            if not stream_url:
                raise RuntimeError("Không lấy được URL âm thanh từ YouTube Music.")
            return stream_url
