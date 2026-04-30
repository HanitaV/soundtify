import yt_dlp
from src.core.accounts import AccountManager
from .base import BaseProvider, Track, extract_stream_headers, extract_stream_url, format_duration

class SoundCloudProvider(BaseProvider):
    def __init__(self):
        self.last_stream_headers: dict[str, str] = {}
        self._auth_token = ""
        self.ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True
        }

    def _saved_token(self) -> str:
        account = AccountManager().connected_platforms().get("soundcloud", {})
        if not isinstance(account, dict):
            return ""
        return str(account.get("access_token") or account.get("token") or "")

    def refresh_auth(self) -> None:
        self._auth_token = self._saved_token()

    def _ydl_opts(self, *, extract_flat: bool) -> dict:
        self.refresh_auth()
        opts = dict(self.ydl_opts)
        opts["extract_flat"] = extract_flat
        if self._auth_token:
            opts["username"] = "oauth"
            opts["password"] = self._auth_token
        return opts

    def search(self, query: str) -> list[Track]:
        search_query = f"scsearch10:{query.strip()}"
        tracks = []
        with yt_dlp.YoutubeDL(self._ydl_opts(extract_flat=True)) as ydl:
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

    def recommendations_for(self, track: Track, limit: int = 20) -> list[Track]:
        query = f"{track.artist} {track.title}".strip()
        if not query:
            return []
        tracks = self.search(query)
        return [item for item in tracks if item.id != track.id][:limit]

    def get_stream_url(self, track_url: str) -> str:
        with yt_dlp.YoutubeDL(self._ydl_opts(extract_flat=False)) as ydl:
            info = ydl.extract_info(track_url, download=False)
            stream_url = extract_stream_url(info)
            if not stream_url:
                raise RuntimeError("Không lấy được URL âm thanh từ SoundCloud.")
            self.last_stream_headers = extract_stream_headers(info, stream_url)
            return stream_url
