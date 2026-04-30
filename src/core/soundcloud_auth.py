from __future__ import annotations

from yt_dlp.cookies import extract_cookies_from_browser


DEFAULT_BROWSERS = ("edge", "chrome", "brave", "firefox")


def extract_soundcloud_token(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if text.startswith("http://") or text.startswith("https://"):
        return ""
    if "code=" in text and "oauth_token=" not in text:
        return ""
    lowered = text.lower()
    if lowered.startswith("oauth "):
        return text.split(" ", 1)[1].strip()
    if lowered.startswith("oauth_token="):
        return text.split("=", 1)[1].split(";", 1)[0].strip()
    if "oauth_token=" in text:
        return text.split("oauth_token=", 1)[1].split(";", 1)[0].strip()
    return text


def soundcloud_token_from_browser(browser: str) -> str:
    jar = extract_cookies_from_browser(browser)
    for item in jar:
        domain = (item.domain or "").lower()
        if "soundcloud.com" in domain and item.name == "oauth_token" and item.value:
            return str(item.value)
    raise RuntimeError("Không tìm thấy oauth_token trong cookie SoundCloud.")


def soundcloud_token_from_any_browser(browsers: tuple[str, ...] = DEFAULT_BROWSERS) -> tuple[str, str]:
    errors = []
    for browser in browsers:
        try:
            return soundcloud_token_from_browser(browser), browser
        except Exception as exc:
            errors.append(f"{browser}: {exc}")
    raise RuntimeError("Không lấy được SoundCloud token từ trình duyệt. " + " | ".join(errors))
