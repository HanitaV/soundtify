import yt_dlp
from .base import BaseProvider, Track, extract_stream_url, format_duration

class SoundCloudProvider(BaseProvider):
    def __init__(self):
        self.ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True
        }

    def search(self, query: str) -> list[Track]:
        search_query = f"scsearch10:{query.strip()}"
        tracks = []
        with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
            try:
                info = ydl.extract_info(search_query, download=False)
                if 'entries' in info:
                    for entry in info['entries']:
                        if not isinstance(entry, dict) or not entry.get('url'):
                            continue
                        tracks.append(Track(
                            id=str(entry['url']),
                            title=entry.get('title', 'Unknown'),
                            artist=entry.get('uploader', 'Unknown'),
                            duration=format_duration(entry.get('duration')),
                            source='SoundCloud'
                        ))
            except Exception as e:
                print(f"Lỗi tìm kiếm SoundCloud: {e}")
        return tracks

    def get_stream_url(self, track_url: str) -> str:
        opts = dict(self.ydl_opts)
        opts['extract_flat'] = False
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(track_url, download=False)
            stream_url = extract_stream_url(info)
            if not stream_url:
                raise RuntimeError("Không lấy được URL âm thanh từ SoundCloud.")
            return stream_url
