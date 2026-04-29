from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(slots=True)
class Track:
    id: str
    title: str
    artist: str
    duration: str
    source: str

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "title": self.title,
            "artist": self.artist,
            "duration": self.duration,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Track":
        return cls(
            id=str(data.get("id", "")),
            title=str(data.get("title", "Unknown")),
            artist=str(data.get("artist", "Unknown")),
            duration=str(data.get("duration", "0:00")),
            source=str(data.get("source", "Unknown")),
        )

class BaseProvider(ABC):
    @abstractmethod
    def search(self, query: str) -> list[Track]:
        pass

    @abstractmethod
    def get_stream_url(self, track_id: str) -> str:
        pass


def format_duration(seconds) -> str:
    try:
        total_seconds = int(float(seconds or 0))
    except (TypeError, ValueError):
        total_seconds = 0

    minutes, remainder = divmod(total_seconds, 60)
    return f"{minutes}:{remainder:02d}"


def parse_duration(duration: str) -> int:
    if not duration:
        return 0

    parts = str(duration).strip().split(":")
    try:
        total = 0
        for part in parts:
            total = total * 60 + int(part)
        return total
    except ValueError:
        return 0


def extract_stream_url(info: dict) -> str:
    if not isinstance(info, dict):
        return ""

    direct_url = info.get("url")
    if isinstance(direct_url, str) and direct_url:
        return direct_url

    for download in info.get("requested_downloads") or []:
        url = download.get("url")
        if isinstance(url, str) and url:
            return url

    formats = info.get("formats") or []
    for item in reversed(formats):
        url = item.get("url")
        if isinstance(url, str) and url:
            return url

    return ""
