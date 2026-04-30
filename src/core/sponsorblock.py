from __future__ import annotations

import json
from dataclasses import dataclass

import requests

from . import debug_log


API_URL = "https://sponsor.ajay.app/api/skipSegments"
DEFAULT_CATEGORIES = ("sponsor",)


@dataclass(slots=True)
class SponsorSegment:
    start: float
    end: float
    category: str


def fetch_segments(video_id: str, categories: tuple[str, ...] = DEFAULT_CATEGORIES) -> list[SponsorSegment]:
    if not video_id or video_id.startswith("http"):
        return []

    try:
        response = requests.get(
            API_URL,
            params={"videoID": video_id, "categories": json.dumps(list(categories))},
            timeout=8,
        )
        if response.status_code == 404:
            debug_log.debug("SponsorBlock has no segments", video_id=video_id)
            return []
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        debug_log.warning("SponsorBlock fetch failed", video_id=video_id, error=str(exc))
        return []

    segments: list[SponsorSegment] = []
    if not isinstance(payload, list):
        return segments

    for item in payload:
        if not isinstance(item, dict):
            continue
        raw_segment = item.get("segment")
        if not isinstance(raw_segment, list) or len(raw_segment) < 2:
            continue
        try:
            start = float(raw_segment[0])
            end = float(raw_segment[1])
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        segments.append(SponsorSegment(start=start, end=end, category=str(item.get("category") or "sponsor")))

    debug_log.debug("SponsorBlock segments loaded", video_id=video_id, count=len(segments))
    return segments
