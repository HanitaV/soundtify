import os
import subprocess
import urllib.request
import zipfile
import shutil
import time
import atexit
from src.core import debug_log
from .security import get_appdata_dir


FFMPEG_ZIP_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
FFMPEG_SHA256_URL = FFMPEG_ZIP_URL + ".sha256"


class Player:
    def __init__(self):
        self.bin_dir = os.path.join(get_appdata_dir(), 'bin')
        os.makedirs(self.bin_dir, exist_ok=True)
        self.ffplay_path = os.path.join(self.bin_dir, 'ffplay.exe')
        self.current_process = None
        self.stream_url = ""
        self.http_headers: dict[str, str] = {}
        self.duration_seconds = 0
        self.offset_seconds = 0
        self.started_at = 0.0
        atexit.register(self.stop)

    def _find_ffplay(self) -> str | None:
        if os.path.exists(self.ffplay_path):
            return self.ffplay_path
        return shutil.which("ffplay")

    def _download_file(self, url: str, destination: str) -> None:
        with urllib.request.urlopen(url, timeout=30) as response:
            with open(destination, "wb") as file:
                shutil.copyfileobj(response, file)

    def _expected_sha256(self) -> str | None:
        try:
            with urllib.request.urlopen(FFMPEG_SHA256_URL, timeout=15) as response:
                content = response.read().decode("utf-8", errors="ignore").strip()
        except Exception:
            return None

        if not content:
            return None
        return content.split()[0].lower()

    def _ensure_ffplay(self) -> bool:
        if self._find_ffplay():
            return True

        print("Đang cài đặt AIO Player (FFplay) lần đầu tiên, vui lòng đợi...")
        zip_path = os.path.join(self.bin_dir, "ffmpeg.zip")

        try:
            self._download_file(FFMPEG_ZIP_URL, zip_path)
            expected_hash = self._expected_sha256()
            if expected_hash:
                from .security import calculate_sha256

                with open(zip_path, "rb") as file:
                    actual_hash = calculate_sha256(file.read())
                if actual_hash.lower() != expected_hash:
                    raise RuntimeError("File FFmpeg tải về không khớp SHA-256.")

            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                for file_info in zip_ref.infolist():
                    if file_info.filename.replace("\\", "/").endswith('/ffplay.exe'):
                        file_info.filename = 'ffplay.exe'
                        zip_ref.extract(file_info, self.bin_dir)
                        break
                else:
                    raise RuntimeError("Không tìm thấy ffplay.exe trong gói FFmpeg.")
            os.remove(zip_path)
            print("Cài đặt AIO Player thành công!")
            return True
        except Exception as e:
            if os.path.exists(zip_path):
                os.remove(zip_path)
            print(f"Lỗi tải AIO Player: {e}")
            return False

    def play(
        self,
        stream_url: str,
        start_seconds: int = 0,
        duration_seconds: int = 0,
        http_headers: dict[str, str] | None = None,
    ) -> bool:
        self.stop()
        if not self._ensure_ffplay():
            print("Trình phát chưa được cài đặt. Không thể phát nhạc.")
            return False

        ffplay = self._find_ffplay()
        safe_start = max(0, int(start_seconds or 0))
        cmd = [ffplay, '-nodisp', '-autoexit', '-loglevel', 'quiet']
        if stream_url.startswith(("http://", "https://")):
            cmd.extend([
                "-reconnect", "1",
                "-reconnect_streamed", "1",
                "-reconnect_on_network_error", "1",
                "-reconnect_delay_max", "8",
            ])
        header_text = self._format_ffmpeg_headers(http_headers or {})
        if header_text:
            cmd.extend(["-headers", header_text])
        if safe_start:
            cmd.extend(['-ss', str(safe_start)])
        cmd.append(stream_url)

        try:
            self.current_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.stream_url = stream_url
            self.http_headers = dict(http_headers or {})
            self.duration_seconds = max(0, int(duration_seconds or 0))
            self.offset_seconds = safe_start
            self.started_at = time.monotonic()
            debug_log.debug(
                "Player started",
                start_seconds=str(safe_start),
                duration_seconds=str(self.duration_seconds),
                is_http=str(stream_url.startswith(("http://", "https://"))),
                header_keys=str(sorted(self.http_headers.keys())),
            )
            return True
        except Exception as e:
            debug_log.exception("Player start failed", error=str(e))
            print(f"Lỗi mở ffplay: {e}")
            self.current_process = None
            return False

    def stop(self):
        if self.current_process:
            if self.current_process.poll() is None:
                self.current_process.terminate()
                try:
                    self.current_process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.current_process.kill()
            self.current_process = None
        self.started_at = 0.0

    def __del__(self):
        self.stop()

    def is_playing(self):
        self._sync_exited_process()
        if self.current_process:
            return self.current_process.poll() is None
        return False

    def elapsed_seconds(self) -> int:
        self._sync_exited_process()
        if not self.started_at:
            return self.offset_seconds

        elapsed = self.offset_seconds
        if self.is_playing():
            elapsed += int(time.monotonic() - self.started_at)

        if self.duration_seconds:
            return min(elapsed, self.duration_seconds)
        return max(0, elapsed)

    def seek_to(self, seconds: int) -> bool:
        if not self.stream_url:
            return False

        target = max(0, int(seconds or 0))
        if self.duration_seconds:
            target = min(target, self.duration_seconds)
        return self.play(self.stream_url, target, self.duration_seconds, self.http_headers)

    def seek_relative(self, seconds: int) -> bool:
        return self.seek_to(self.elapsed_seconds() + int(seconds or 0))

    def progress_ratio(self) -> float:
        if not self.duration_seconds:
            return 0.0
        return min(1.0, self.elapsed_seconds() / self.duration_seconds)

    def ended_early(self, grace_seconds: int = 8) -> bool:
        self._sync_exited_process()
        if not self.current_process or self.current_process.poll() is None:
            return False
        if not self.duration_seconds or not self.stream_url.startswith(("http://", "https://")):
            return False
        return self.offset_seconds < max(0, self.duration_seconds - grace_seconds)

    def finished(self, grace_seconds: int = 3) -> bool:
        self._sync_exited_process()
        if not self.current_process or self.current_process.poll() is None:
            return False
        if self.duration_seconds:
            return self.offset_seconds >= max(0, self.duration_seconds - grace_seconds)
        return self.offset_seconds > 0

    def _sync_exited_process(self) -> None:
        if not self.current_process or self.current_process.poll() is None or not self.started_at:
            return
        self.offset_seconds = max(0, self.offset_seconds + int(time.monotonic() - self.started_at))
        if self.duration_seconds:
            self.offset_seconds = min(self.offset_seconds, self.duration_seconds)
        self.started_at = 0.0
        debug_log.warning(
            "Player process exited",
            returncode=str(self.current_process.returncode),
            offset_seconds=str(self.offset_seconds),
            duration_seconds=str(self.duration_seconds),
        )

    def _format_ffmpeg_headers(self, headers: dict[str, str]) -> str:
        lines = []
        for key, value in headers.items():
            safe_key = str(key).strip()
            safe_value = str(value).replace("\r", " ").replace("\n", " ").strip()
            if not safe_key or not safe_value:
                continue
            lines.append(f"{safe_key}: {safe_value}\r\n")
        return "".join(lines)
