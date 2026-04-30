from __future__ import annotations

from http.cookies import SimpleCookie
from typing import Any

from yt_dlp.cookies import extract_cookies_from_browser
from ytmusicapi.helpers import get_authorization, initialize_headers

from . import debug_log


YTMUSIC_ORIGIN = "https://music.youtube.com"
YTMUSIC_REFERER = "https://music.youtube.com/"
SENSITIVE_COOKIE_NAMES = ("__Secure-3PAPISID", "SAPISID", "__Secure-1PAPISID")
DEFAULT_BROWSERS = ("edge", "chrome", "brave", "firefox")


def extract_cookie_from_input(value: str) -> str:
    text = value.strip()
    if not text:
        return ""

    header_values: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith("cookie:"):
            header_values.append(line.split(":", 1)[1].strip())
            continue
        if line.lower() == "cookie":
            continue
        if "=" in line and not line.startswith(":"):
            header_values.append(line)

    if header_values:
        cookie = "; ".join(header_values)
        debug_log.debug("Parsed cookie from header lines", names=",".join(parse_cookie(cookie).keys()))
        return cookie

    if "=" in text:
        cookie = text.removeprefix("Cookie:").removeprefix("cookie:").strip()
        debug_log.debug("Parsed cookie from raw input", names=",".join(parse_cookie(cookie).keys()))
        return cookie

    return ""


def parse_cookie(cookie: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in cookie.split(";"):
        name, separator, value = part.strip().partition("=")
        if separator and name:
            result[name] = value
    return result


def cookie_sapisid(cookie: str) -> str:
    values = parse_cookie(cookie)
    for name in SENSITIVE_COOKIE_NAMES:
        value = values.get(name)
        if value:
            return value
    return ""


def normalize_cookie(cookie: str) -> str:
    clean = extract_cookie_from_input(cookie) or cookie.strip()
    if not clean:
        return ""

    values = parse_cookie(clean)
    sapisid = cookie_sapisid(clean)
    if sapisid and "__Secure-3PAPISID" not in values:
        clean = f"{clean}; __Secure-3PAPISID={sapisid}"
    return clean


def validate_ytmusic_cookie(cookie: str) -> str:
    clean = normalize_cookie(cookie)
    debug_log.debug("Validating ytmusic cookie", names=",".join(parse_cookie(clean).keys()))
    if not clean:
        raise ValueError("Thiếu cookie YouTube Music.")
    if not cookie_sapisid(clean):
        raise ValueError("Cookie YouTube Music cần SAPISID hoặc __Secure-3PAPISID.")

    parsed = SimpleCookie()
    parsed.load(clean.replace('"', ""))
    if "__Secure-3PAPISID" not in parsed:
        raise ValueError("Không đọc được __Secure-3PAPISID từ cookie.")
    return clean


def make_ytmusic_auth_headers(cookie: str) -> dict[str, Any]:
    clean = validate_ytmusic_cookie(cookie)
    headers = dict(initialize_headers())
    headers.update(
        {
            "cookie": clean,
            "origin": YTMUSIC_ORIGIN,
            "referer": YTMUSIC_REFERER,
            "x-goog-authuser": "0",
            "authorization": get_authorization(f"{cookie_sapisid(clean)} {YTMUSIC_ORIGIN}"),
        }
    )
    return headers


def cookie_from_browser(browser: str) -> str:
    debug_log.info("Trying ytmusic browser cookie import", browser=browser)
    jar = extract_cookies_from_browser(browser)
    pairs: list[str] = []
    for item in jar:
        domain = (item.domain or "").lower()
        if "youtube.com" not in domain and "google.com" not in domain:
            continue
        name = item.name or ""
        value = item.value or ""
        if name and value:
            pairs.append(f"{name}={value}")
    cookie = "; ".join(dict.fromkeys(pairs))
    result = validate_ytmusic_cookie(cookie)
    debug_log.info("Imported ytmusic browser cookie", browser=browser, cookie_count=str(len(parse_cookie(result))))
    return result


def cookie_from_any_browser(browsers: tuple[str, ...] = DEFAULT_BROWSERS) -> tuple[str, str]:
    errors = []
    for browser in browsers:
        try:
            return cookie_from_browser(browser), browser
        except Exception as exc:
            errors.append(f"{browser}: {exc}")
    raise RuntimeError("Không lấy được YouTube Music cookie từ trình duyệt. " + " | ".join(errors))


def cookie_label(cookie: str) -> str:
    values = parse_cookie(cookie)
    if "__Secure-3PAPISID" in values:
        return "YouTube Music browser cookie"
    if "SAPISID" in values:
        return "YouTube Music SAPISID cookie"
    return "YouTube Music cookie"
