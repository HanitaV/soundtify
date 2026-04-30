from __future__ import annotations

import argparse
import html
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
START_MARKER = "<!-- CLI_CAPTURE_START -->"
END_MARKER = "<!-- CLI_CAPTURE_END -->"


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture Soundtify classic CLI preview as an SVG.")
    parser.add_argument("--python", default=sys.executable, help="Python executable to use.")
    parser.add_argument("--output", default="docs/assets/cli-preview.svg", help="SVG output path.")
    parser.add_argument("--readme", default="README.md", help="README path to update.")
    args = parser.parse_args()

    output = Path(args.output)
    readme = Path(args.readme)
    text = capture_cli(args.python)
    lines = select_lines(text)
    write_svg(output, lines)
    update_readme(readme, output.as_posix())
    print(f"Captured CLI preview to {output}")
    print(f"Updated README block in {readme}")
    return 0


def capture_cli(python_executable: str) -> str:
    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    env["TERM"] = "dumb"
    command = [python_executable, "main.py", "--classic"]
    try:
        with tempfile.TemporaryDirectory(prefix="soundtify-cli-capture-") as appdata:
            env["APPDATA"] = appdata
            result = subprocess.run(
                command,
                input="help\nq\n",
                text=True,
                capture_output=True,
                timeout=30,
                env=env,
                encoding="utf-8",
                errors="replace",
            )
    except Exception as exc:
        return fallback_capture(f"capture failed: {exc}")

    combined = "\n".join(part for part in (result.stdout, result.stderr) if part)
    if not combined.strip():
        return fallback_capture("capture produced no output")
    return clean_terminal_text(combined)


def fallback_capture(reason: str) -> str:
    return "\n".join(
        [
            "SOUNDTIFY CLI",
            "AIO Player nhẹ RAM | Nguồn: YTMUSIC | Playlist: default",
            "",
            "Lệnh: search/s, suggest/g, add, queue, playlist/pl, now, seek/tua, next/n, back/b, provider, login, sync, help, quit",
            "",
            "soundtify> help",
            "search/s <từ khóa>        Tìm nhạc và chọn bài để phát",
            "seek/tua <+giây|-giây|m:ss>  Tua bài hiện tại",
            "login ytmusic             Tự lấy cookie YouTube Music từ browser",
            "soundtify> q",
            "Tạm biệt!",
            f"[{reason}]",
        ]
    )


def clean_terminal_text(value: str) -> str:
    text = ANSI_RE.sub("", value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = CONTROL_RE.sub("", text)
    text = text.replace("soundtify> \nLệnh", "soundtify> help\nLệnh")
    text = text.replace("soundtify> Tạm biệt!", "soundtify> q\nTạm biệt!")
    return text


def select_lines(text: str, limit: int = 24, width: int = 96) -> list[str]:
    raw_lines = [line.rstrip() for line in text.splitlines()]
    useful = []
    for line in raw_lines:
        stripped = line.strip()
        if not stripped:
            if useful and useful[-1]:
                useful.append("")
            continue
        if stripped in {"[?25l", "[?25h"}:
            continue
        useful.append(stripped)

    if not useful:
        useful = fallback_capture("empty capture").splitlines()

    compact = []
    for index, line in enumerate(useful):
        next_line = useful[index + 1] if index + 1 < len(useful) else ""
        if line == "soundtify>" and next_line.startswith("Lệnh"):
            line = "soundtify> help"
        line = re.sub(r"\s{3,}", "  ", line)
        compact.append(line[:width])

    if len(compact) > limit:
        head = compact[: limit - 3]
        tail = compact[-2:]
        compact = head + ["..."] + tail
    return compact


def write_svg(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    width = 980
    line_height = 22
    top = 72
    height = top + max(1, len(lines)) * line_height + 28
    body = []
    for index, line in enumerate(lines):
        y = top + index * line_height
        escaped = html.escape(line)
        color = "#ff8a3d" if "soundtify>" in line or "SOUNDTIFY" in line else "#e7e7e7"
        body.append(f'<text x="28" y="{y}" fill="{color}">{escaped}</text>')

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Soundtify CLI preview">
  <rect width="100%" height="100%" rx="12" fill="#101010"/>
  <rect x="0" y="0" width="100%" height="44" rx="12" fill="#1d1d1d"/>
  <circle cx="26" cy="22" r="6" fill="#ff5f56"/>
  <circle cx="46" cy="22" r="6" fill="#ffbd2e"/>
  <circle cx="66" cy="22" r="6" fill="#27c93f"/>
  <text x="92" y="28" fill="#bdbdbd" font-family="Consolas, 'Cascadia Mono', monospace" font-size="14">soundtify --classic</text>
  <g font-family="Consolas, 'Cascadia Mono', monospace" font-size="15">
    {chr(10).join(body)}
  </g>
</svg>
"""
    path.write_text(svg, encoding="utf-8", newline="\n")


def update_readme(path: Path, svg_path: str) -> None:
    tui_path = Path("docs/assets/tui-preview.svg")
    tui_lines = []
    if tui_path.exists():
        tui_lines = [
            "### TUI Home",
            "",
            f'![Soundtify TUI preview]({tui_path.as_posix()})',
            "",
        ]
    image_block = "\n".join(
        [
            START_MARKER,
            "## Preview",
            "",
            *tui_lines,
            "### Classic CLI",
            "",
            f'![Soundtify CLI preview]({svg_path})',
            END_MARKER,
        ]
    )
    text = path.read_text(encoding="utf-8")
    if START_MARKER in text and END_MARKER in text:
        pattern = re.compile(f"{re.escape(START_MARKER)}.*?{re.escape(END_MARKER)}", re.DOTALL)
        updated = pattern.sub(image_block, text)
    else:
        anchor = "## 🚀 Cài đặt và Sử dụng"
        if anchor in text:
            updated = text.replace(anchor, f"{image_block}\n\n{anchor}", 1)
        else:
            updated = f"{image_block}\n\n{text}"
    path.write_text(updated, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    raise SystemExit(main())
