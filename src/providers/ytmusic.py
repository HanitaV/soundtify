from ytmusicapi import YTMusic
import yt_dlp
import json
import re
import requests
from dataclasses import dataclass
from src.core import debug_log
from src.core.accounts import AccountManager
from src.core.ytmusic_auth import make_ytmusic_auth_headers
from .base import BaseProvider, LyricLine, Track, extract_stream_headers, extract_stream_url


@dataclass(slots=True)
class ArtistChannel:
    id: str
    name: str
    subtitle: str = ""
    source: str = "YTMusic"


class YTMusicProvider(BaseProvider):
    def __init__(self):
        self._auth_cookie = ""
        self.last_stream_headers: dict[str, str] = {}
        self.ytmusic = self._make_client()
        self.ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'noplaylist': True,
        }

    def _saved_cookie(self) -> str:
        account = AccountManager().connected_platforms().get("ytmusic", {})
        if not isinstance(account, dict):
            return ""
        return str(account.get("cookie") or "")

    def _make_client(self) -> YTMusic:
        cookie = self._saved_cookie()
        self._auth_cookie = cookie
        if not cookie:
            debug_log.debug("Creating anonymous YTMusic client")
            return YTMusic()
        debug_log.debug("Creating authenticated YTMusic client")
        return YTMusic(auth=make_ytmusic_auth_headers(cookie))

    def refresh_auth(self) -> None:
        cookie = self._saved_cookie()
        if cookie != self._auth_cookie:
            self.ytmusic = self._make_client()

    def _ydl_opts(self) -> dict:
        self.refresh_auth()
        opts = dict(self.ydl_opts)
        if self._auth_cookie:
            opts["http_headers"] = {"Cookie": self._auth_cookie}
        return opts

    def search(self, query: str) -> list[Track]:
        self.refresh_auth()
        debug_log.info("YTMusic search", query=query, authenticated=str(bool(self._auth_cookie)))
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

    def search_suggestions(self, query: str, limit: int = 8) -> list[str]:
        self.refresh_auth()
        text = query.strip()
        if len(text) < 2:
            return []
        try:
            results = self.ytmusic.get_search_suggestions(text)
        except Exception as exc:
            debug_log.warning("YTMusic suggestions failed", query=text, error=str(exc))
            return []

        suggestions: list[str] = []
        seen = set()
        for item in results:
            suggestion = str(item).strip()
            key = suggestion.casefold()
            if suggestion and key not in seen:
                suggestions.append(suggestion)
                seen.add(key)
            if len(suggestions) >= limit:
                break
        return suggestions

    def recommendations_for(self, track: Track, limit: int = 20) -> list[Track]:
        self.refresh_auth()
        debug_log.info("YTMusic recommendations", track_id=track.id, limit=str(limit))
        try:
            watch = self.ytmusic.get_watch_playlist(videoId=track.id, limit=limit + 5)
        except Exception as exc:
            debug_log.warning("YTMusic recommendations failed", track_id=track.id, error=str(exc))
            return []

        items = watch.get("tracks") if isinstance(watch, dict) else []
        tracks = self._tracks_from_items(items or [], limit + 5)
        return [
            item for item in tracks
            if (item.id, item.source) != (track.id, "YTMusic")
        ][:limit]

    def search_artists(self, query: str) -> list[ArtistChannel]:
        self.refresh_auth()
        debug_log.info("YTMusic artist search", query=query, authenticated=str(bool(self._auth_cookie)))
        results = self.ytmusic.search(query.strip(), filter='artists', limit=10)
        artists: list[ArtistChannel] = []
        for item in results:
            artist_id = str(item.get("browseId") or item.get("channelId") or "")
            name = str(item.get("artist") or item.get("title") or item.get("name") or "Unknown")
            if not artist_id:
                continue
            subtitle = str(item.get("subscribers") or item.get("subtitle") or item.get("category") or "")
            artists.append(ArtistChannel(id=artist_id, name=name, subtitle=subtitle))
        return artists

    def artist_popular_tracks(self, artist_id: str, limit: int = 25) -> list[Track]:
        self.refresh_auth()
        debug_log.info("YTMusic artist popular tracks", artist_id=artist_id)
        artist = self.ytmusic.get_artist(artist_id)
        songs = artist.get("songs") if isinstance(artist, dict) else {}
        results = []
        if isinstance(songs, dict):
            browse_id = songs.get("browseId")
            if browse_id:
                try:
                    playlist = self.ytmusic.get_playlist(str(browse_id), limit=limit)
                    results = playlist.get("tracks") or []
                except Exception as exc:
                    debug_log.warning("Artist popular playlist fallback", error=str(exc))
            if not results:
                results = songs.get("results") or []
        return self._tracks_from_items(results, limit)

    def artist_newest_tracks(self, artist_id: str, limit: int = 25) -> list[Track]:
        self.refresh_auth()
        debug_log.info("YTMusic artist newest tracks", artist_id=artist_id)
        artist = self.ytmusic.get_artist(artist_id)
        tracks: list[Track] = []
        for section_name in ("singles", "albums"):
            section = artist.get(section_name) if isinstance(artist, dict) else {}
            if not isinstance(section, dict):
                continue
            browse_id = section.get("browseId")
            params = section.get("params")
            releases = section.get("results") or []
            if browse_id and params:
                try:
                    releases = self.ytmusic.get_artist_albums(str(browse_id), str(params), limit=8, order="Recency")
                except Exception as exc:
                    debug_log.warning("Artist releases fallback", section=section_name, error=str(exc))
            for release in releases[:8]:
                album_id = release.get("browseId") if isinstance(release, dict) else ""
                if not album_id:
                    continue
                try:
                    album = self.ytmusic.get_album(str(album_id))
                except Exception as exc:
                    debug_log.warning("Artist album fetch failed", album_id=str(album_id), error=str(exc))
                    continue
                tracks.extend(self._tracks_from_items(album.get("tracks") or [], limit))
                if len(tracks) >= limit:
                    return tracks[:limit]
        if not tracks:
            return self.artist_popular_tracks(artist_id, limit)
        return self._unique_tracks(tracks)[:limit]

    def _tracks_from_items(self, items, limit: int = 25) -> list[Track]:
        tracks: list[Track] = []
        if not isinstance(items, list):
            return tracks
        for item in items:
            if not isinstance(item, dict):
                continue
            video_id = item.get("videoId")
            if not video_id:
                continue
            artist_names = [
                artist.get('name')
                for artist in item.get('artists', [])
                if isinstance(artist, dict) and artist.get('name')
            ]
            tracks.append(Track(
                id=str(video_id),
                title=str(item.get("title") or "Unknown"),
                artist=", ".join(artist_names) or str(item.get("artist") or "Unknown"),
                duration=str(item.get("duration") or "0:00"),
                source="YTMusic",
            ))
            if len(tracks) >= limit:
                break
        return self._unique_tracks(tracks)

    def _unique_tracks(self, tracks: list[Track]) -> list[Track]:
        seen = set()
        result = []
        for track in tracks:
            if track.id in seen:
                continue
            seen.add(track.id)
            result.append(track)
        return result

    def get_stream_url(self, track_id: str) -> str:
        url = f"https://music.youtube.com/watch?v={track_id}"
        debug_log.info("YTMusic stream resolve", track_id=track_id, authenticated=str(bool(self._auth_cookie)))
        with yt_dlp.YoutubeDL(self._ydl_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
            stream_url = extract_stream_url(info)
            if not stream_url:
                raise RuntimeError("Không lấy được URL âm thanh từ YouTube Music.")
            self.last_stream_headers = extract_stream_headers(info, stream_url)
            debug_log.debug(
                "YTMusic stream resolved",
                track_id=track_id,
                headers=str(sorted(self.last_stream_headers.keys())),
            )
            return stream_url

    def get_lyrics(self, track_id: str) -> list[LyricLine]:
        self.refresh_auth()
        debug_log.info("YTMusic lyrics resolve", track_id=track_id)
        lines = self._ytmusic_lyrics(track_id)
        if lines:
            return lines
        return self._caption_lyrics(track_id)

    def _ytmusic_lyrics(self, track_id: str) -> list[LyricLine]:
        try:
            watch = self.ytmusic.get_watch_playlist(videoId=track_id, limit=1)
            browse_id = watch.get("lyrics") if isinstance(watch, dict) else ""
            if not browse_id:
                return []
            raw = self.ytmusic.get_lyrics(str(browse_id), timestamps=True)
        except Exception as exc:
            debug_log.warning("YTMusic lyrics fetch failed", track_id=track_id, error=str(exc))
            return []

        source = str(getattr(raw, "source", "") or "YouTube Music lyrics")
        lyrics = getattr(raw, "lyrics", None)
        if isinstance(lyrics, str):
            return [LyricLine(text=line.strip(), source=source) for line in lyrics.splitlines() if line.strip()]

        lines: list[LyricLine] = []
        if isinstance(lyrics, list):
            for item in lyrics:
                text = str(getattr(item, "text", "") or "").strip()
                if not text:
                    continue
                start = self._normalise_lyric_time(getattr(item, "start_time", None))
                end = self._normalise_lyric_time(getattr(item, "end_time", None))
                lines.append(LyricLine(text=text, start_seconds=start, end_seconds=end, source=source))
        return lines

    def _caption_lyrics(self, track_id: str) -> list[LyricLine]:
        url = f"https://music.youtube.com/watch?v={track_id}"
        try:
            with yt_dlp.YoutubeDL(self._ydl_opts()) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as exc:
            debug_log.warning("Caption metadata fetch failed", track_id=track_id, error=str(exc))
            return []

        caption = self._best_caption(info)
        if not caption:
            return []
        caption_url = caption.get("url")
        if not caption_url:
            return []
        try:
            response = requests.get(caption_url, timeout=12)
            response.raise_for_status()
        except Exception as exc:
            debug_log.warning("Caption download failed", track_id=track_id, error=str(exc))
            return []

        ext = str(caption.get("ext") or "")
        source = f"YouTube subtitles ({caption.get('language') or 'unknown'})"
        if ext == "json3" or response.text.lstrip().startswith("{"):
            return self._parse_json3_captions(response.text, source)
        return self._parse_vtt_captions(response.text, source)

    def _best_caption(self, info: dict) -> dict:
        if not isinstance(info, dict):
            return {}
        pools = []
        captions = info.get("subtitles") or {}
        if isinstance(captions, dict):
            for language, formats in captions.items():
                if isinstance(formats, list):
                    for item in formats:
                        if isinstance(item, dict):
                            candidate = dict(item)
                            candidate["language"] = language
                            pools.append(candidate)
        language_rank = {"vi": 0, "en": 1, "en-US": 2, "a.en": 3}
        ext_rank = {"json3": 0, "vtt": 1, "srv3": 2, "ttml": 3}
        pools.sort(key=lambda item: (
            language_rank.get(str(item.get("language")), 10),
            ext_rank.get(str(item.get("ext")), 9),
        ))
        return pools[0] if pools else {}

    def _parse_json3_captions(self, text: str, source: str) -> list[LyricLine]:
        try:
            data = json.loads(text)
        except ValueError:
            return []
        lines: list[LyricLine] = []
        for event in data.get("events") or []:
            if not isinstance(event, dict):
                continue
            pieces = event.get("segs") or []
            line = "".join(str(piece.get("utf8") or "") for piece in pieces if isinstance(piece, dict))
            line = re.sub(r"\s+", " ", line).strip()
            if not line:
                continue
            start = self._normalise_lyric_time(event.get("tStartMs"))
            duration_ms = event.get("dDurationMs")
            end = start + int(duration_ms / 1000) if start is not None and isinstance(duration_ms, (int, float)) else None
            lines.append(LyricLine(text=line, start_seconds=start, end_seconds=end, source=source))
        return lines

    def _parse_vtt_captions(self, text: str, source: str) -> list[LyricLine]:
        lines: list[LyricLine] = []
        blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n"))
        for block in blocks:
            raw_lines = [line.strip() for line in block.splitlines() if line.strip()]
            timing = next((line for line in raw_lines if "-->" in line), "")
            if not timing:
                continue
            start_text, _, end_text = timing.partition("-->")
            content = " ".join(line for line in raw_lines if "-->" not in line and not line.isdigit())
            content = re.sub(r"<[^>]+>", "", content)
            content = re.sub(r"\s+", " ", content).strip()
            if not content:
                continue
            lines.append(
                LyricLine(
                    text=content,
                    start_seconds=self._parse_caption_time(start_text.strip()),
                    end_seconds=self._parse_caption_time(end_text.strip().split()[0]),
                    source=source,
                )
            )
        return lines

    def _parse_caption_time(self, value: str) -> int | None:
        match = re.match(r"(?:(\d+):)?(\d+):(\d+)(?:[.,](\d+))?", value)
        if not match:
            return None
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)
        return hours * 3600 + minutes * 60 + seconds

    def _normalise_lyric_time(self, value) -> int | None:
        if value is None:
            return None
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            return None
        return max(0, int(number / 1000))
