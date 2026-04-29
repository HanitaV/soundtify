import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from src.core.accounts import AccountManager, SUPPORTED_PLATFORMS
from src.core.library import LibraryManager
from src.core.player import Player
from src.core.security import secure_load_json, secure_save_json
from src.providers import SoundCloudProvider, SpotifyProvider, YTMusicProvider
from src.providers.base import Track, format_duration, parse_duration


console = Console()
CACHE_FILE = "search_cache.json"
MAX_CACHE_ENTRIES = 50


class SoundtifyApp:
    def __init__(self):
        self.player = Player()
        self.providers = {
            "ytmusic": YTMusicProvider(),
            "soundcloud": SoundCloudProvider(),
            "spotify": SpotifyProvider(),
        }
        self.current_provider = self.providers["ytmusic"]
        self.provider_name = "ytmusic"
        self.current_track: Track | None = None
        self.search_results: list[Track] = []
        self.session = None
        self.library = LibraryManager()
        self.accounts = AccountManager()
        self.search_cache = secure_load_json(CACHE_FILE)
        if not isinstance(self.search_cache, dict):
            self.search_cache = {}

    def _prompt(self, message: str, completer=None) -> str:
        try:
            if self.session is None:
                self.session = PromptSession(completer=completer)
            return self.session.prompt(message, completer=completer)
        except Exception:
            self.session = None
            return input(message)

    def show_dashboard(self):
        console.clear()
        banner = Text("🎵 SOUNDTIFY CLI 🎵", style="bold magenta", justify="center")
        console.print(Panel(banner, border_style="cyan"))
        console.print(
            f"[green]AIO Player nhẹ RAM[/green] | Nguồn: [bold yellow]{self.provider_name.upper()}[/bold yellow] | "
            f"Playlist: [bold cyan]{self.library.active_playlist_name}[/bold cyan]\n"
        )
        console.print(Columns([self._now_playing_panel(), self._playlist_panel(), self._account_panel()], expand=True))
        console.print(
            "\n[dim]Lệnh: search/s, suggest/g, add, queue, playlist/pl, now, seek/tua, next/n, back/b, "
            "provider, login, sync, help, quit[/dim]\n"
        )

    def _now_playing_panel(self) -> Panel:
        if not self.current_track:
            return Panel("Chưa phát bài nào.", title="Now Playing", border_style="green")

        elapsed = self.player.elapsed_seconds()
        duration = parse_duration(self.current_track.duration)
        progress = self._progress_bar(elapsed, duration)
        status = "Đang phát" if self.player.is_playing() else "Đã dừng"
        body = (
            f"[bold]{self.current_track.title}[/bold]\n"
            f"{self.current_track.artist}\n"
            f"[dim]{self.current_track.source} | {status}[/dim]\n\n"
            f"{progress} {format_duration(elapsed)} / {self.current_track.duration}"
        )
        return Panel(body, title="Now Playing", border_style="green")

    def _playlist_panel(self) -> Panel:
        table = Table.grid(expand=True)
        table.add_column(ratio=1)
        queue = self.library.queue[:3]
        playlist = self.library.active_playlist[:5]

        if queue:
            table.add_row("[bold yellow]Queue[/bold yellow]")
            for idx, track in enumerate(queue, start=1):
                table.add_row(f"{idx}. {track.title} [dim]- {track.artist}[/dim]")

        table.add_row("[bold cyan]Playlist[/bold cyan]")
        if playlist:
            for idx, track in enumerate(playlist, start=1):
                table.add_row(f"{idx}. {track.title} [dim]- {track.artist}[/dim]")
        else:
            table.add_row("[dim]Playlist trống. Dùng add <số> pl[/dim]")
        return Panel(table, title="Playlist", border_style="cyan")

    def _account_panel(self) -> Panel:
        accounts = self.accounts.connected_platforms()
        if not accounts:
            body = "Chưa đăng nhập.\n[dim]login <platform> <label>[/dim]"
        else:
            lines = []
            for platform, account in accounts.items():
                last_sync = account.get("last_sync") or "chưa sync"
                lines.append(f"[bold]{platform}[/bold]: {account.get('label', platform)}\n[dim]{last_sync}[/dim]")
            body = "\n".join(lines)
        return Panel(body, title="Accounts", border_style="magenta")

    def _progress_bar(self, elapsed: int, duration: int, width: int = 22) -> str:
        if duration <= 0:
            return "[" + "-" * width + "]"
        filled = min(width, max(0, int(width * elapsed / duration)))
        return "[" + "#" * filled + "-" * (width - filled) + "]"

    def _cache_key(self, query: str) -> str:
        return f"{self.provider_name}:{query.strip().casefold()}"

    def _get_cached_results(self, query: str) -> list[Track] | None:
        raw_tracks = self.search_cache.get(self._cache_key(query))
        if not isinstance(raw_tracks, list):
            return None
        tracks = [Track.from_dict(item) for item in raw_tracks if isinstance(item, dict)]
        return tracks or None

    def _save_cached_results(self, query: str, tracks: list[Track]) -> None:
        self.search_cache[self._cache_key(query)] = [track.to_dict() for track in tracks]
        while len(self.search_cache) > MAX_CACHE_ENTRIES:
            oldest_key = next(iter(self.search_cache))
            self.search_cache.pop(oldest_key, None)
        secure_save_json(CACHE_FILE, self.search_cache)

    def _provider_for_track(self, track: Track):
        source = track.source.lower()
        if "soundcloud" in source:
            return "soundcloud", self.providers["soundcloud"]
        if "spotify" in source:
            return "spotify", self.providers["spotify"]
        return "ytmusic", self.providers["ytmusic"]

    def _print_tracks(self, tracks: list[Track], title: str) -> None:
        table = Table(show_header=True, header_style="bold green", box=box.SIMPLE)
        table.add_column("STT", style="dim", width=4)
        table.add_column("Tên bài hát", style="cyan")
        table.add_column("Nghệ sĩ", style="magenta")
        table.add_column("Nguồn", style="yellow")
        table.add_column("Thời lượng", justify="right")
        for idx, track in enumerate(tracks, start=1):
            table.add_row(str(idx), track.title, track.artist, track.source, track.duration)
        console.print(Panel(table, title=title, border_style="cyan"))

    def _track_from_results(self, index_text: str) -> Track | None:
        if not index_text.isdigit():
            return None
        index = int(index_text)
        if 1 <= index <= len(self.search_results):
            return self.search_results[index - 1]
        return None

    def search_and_play(self, query: str):
        query = query.strip()
        if not query:
            console.print("[red]Vui lòng nhập từ khóa. Ví dụ: search son tung[/red]")
            return

        console.print(f"[cyan]Đang tìm kiếm '{query}' trên {self.provider_name.upper()}...[/cyan]")
        try:
            cached_results = self._get_cached_results(query)
            if cached_results:
                self.search_results = cached_results
                console.print("[dim]Dùng kết quả từ cache đã xác minh SHA-256.[/dim]")
            else:
                self.search_results = self.current_provider.search(query)
                self._save_cached_results(query, self.search_results)

            if not self.search_results:
                console.print("[red]Không tìm thấy kết quả nào.[/red]")
                return

            self._print_tracks(self.search_results, "Kết quả tìm kiếm")
            choice = self._prompt("Số để phát, 'a <số>' thêm queue, 'p <số>' thêm playlist, Enter hủy: ").strip()
            if choice.isdigit():
                track = self._track_from_results(choice)
                if track:
                    self.play_track(track)
            elif choice.lower().startswith("a "):
                self.add_result_to_queue(choice[2:].strip())
            elif choice.lower().startswith("p "):
                self.add_result_to_playlist(choice[2:].strip())
            elif choice:
                console.print("[yellow]Lựa chọn không hợp lệ, đã hủy.[/yellow]")
        except Exception as e:
            console.print(f"[red]Lỗi khi tìm kiếm: {e}[/red]")

    def add_result_to_queue(self, index_text: str):
        track = self._track_from_results(index_text)
        if not track:
            console.print("[red]Không tìm thấy STT trong kết quả gần nhất.[/red]")
            return
        self.library.add_to_queue(track)
        console.print(f"[green]Đã thêm vào queue: {track.title}[/green]")

    def add_result_to_playlist(self, index_text: str, playlist_name: str | None = None):
        track = self._track_from_results(index_text)
        if not track:
            console.print("[red]Không tìm thấy STT trong kết quả gần nhất.[/red]")
            return
        name = self.library.add_to_playlist(track, playlist_name)
        console.print(f"[green]Đã thêm vào playlist '{name}': {track.title}[/green]")

    def play_track(self, track: Track, start_seconds: int = 0):
        provider_name, provider = self._provider_for_track(track)
        console.print(f"[yellow]Đang lấy luồng âm thanh cho: {track.title}...[/yellow]")
        try:
            url = provider.get_stream_url(track.id)
            if not url:
                raise RuntimeError("Provider không trả về URL âm thanh.")

            duration_seconds = parse_duration(track.duration)
            if self.player.play(url, start_seconds, duration_seconds):
                self.current_track = track
                self.provider_name = provider_name
                self.current_provider = provider
                self.library.add_to_history(track)
                console.print(f"[bold green]▶ Đang phát: {track.title} - {track.artist}[/bold green]")
                console.print("[dim]Lệnh nhanh: seek +30, seek -15, next, back, now, stop[/dim]")
        except Exception as e:
            console.print(f"[red]Lỗi khi phát nhạc: {e}[/red]")

    def next_track(self):
        next_item = self.library.pop_next_queue()
        if next_item:
            self.play_track(next_item)
            return

        playlist = self.library.active_playlist
        if not playlist:
            console.print("[yellow]Queue và playlist đang trống.[/yellow]")
            return

        if not self.current_track:
            self.play_track(playlist[0])
            return

        current_index = next((idx for idx, item in enumerate(playlist) if item.id == self.current_track.id), -1)
        next_index = (current_index + 1) % len(playlist)
        self.play_track(playlist[next_index])

    def back_track(self):
        history = self.library.history
        if len(history) < 2:
            console.print("[yellow]Chưa có bài trước đó.[/yellow]")
            return
        self.play_track(history[1])

    def seek(self, value: str):
        if not self.current_track:
            console.print("[yellow]Chưa có bài đang phát để tua.[/yellow]")
            return

        value = value.strip()
        if not value:
            console.print("[red]Ví dụ: seek +30, seek -15, seek 1:20[/red]")
            return

        if value.startswith(("+", "-")):
            if not value[1:].isdigit():
                console.print("[red]Giá trị tua không hợp lệ.[/red]")
                return
            success = self.player.seek_relative(int(value))
        else:
            target = parse_duration(value) if ":" in value else int(value) if value.isdigit() else -1
            if target < 0:
                console.print("[red]Giá trị tua không hợp lệ.[/red]")
                return
            success = self.player.seek_to(target)

        if success:
            console.print(f"[green]Đã tua tới {format_duration(self.player.elapsed_seconds())}.[/green]")
        else:
            console.print("[red]Không tua được bài hiện tại.[/red]")

    def suggest(self, query: str = ""):
        if query.strip():
            suggestion_query = query.strip()
        elif self.current_track:
            suggestion_query = f"{self.current_track.artist} {self.current_track.title}"
        else:
            console.print("[yellow]Chưa có bài đang phát. Dùng suggest <từ khóa>.[/yellow]")
            return

        console.print(f"[cyan]Đang gợi ý bài liên quan: {suggestion_query}[/cyan]")
        self.search_results = self.current_provider.search(suggestion_query)
        if not self.search_results:
            console.print("[red]Không có gợi ý phù hợp.[/red]")
            return
        self._print_tracks(self.search_results, "Gợi ý bài")

    def show_queue(self, args: str = ""):
        parts = args.split()
        action = parts[0].lower() if parts else ""
        if action == "clear":
            self.library.clear_queue()
            console.print("[green]Đã xóa toàn bộ queue.[/green]")
            return
        if action == "remove" and len(parts) > 1 and parts[1].isdigit():
            removed = self.library.remove_from_queue(int(parts[1]))
            if removed:
                console.print(f"[green]Đã xóa khỏi queue: {removed.title}[/green]")
            else:
                console.print("[red]STT queue không hợp lệ.[/red]")
            return

        queue = self.library.queue
        if not queue:
            console.print("[yellow]Queue đang trống.[/yellow]")
            return
        self._print_tracks(queue, "Queue")

    def show_playlist(self):
        playlist = self.library.active_playlist
        playlists = self.library.list_playlists()
        console.print(f"[bold cyan]Playlist hiện tại:[/bold cyan] {self.library.active_playlist_name}")
        console.print("[dim]" + ", ".join(f"{name} ({count})" for name, count in playlists.items()) + "[/dim]")
        if playlist:
            self._print_tracks(playlist, "Playlist")
        else:
            console.print("[yellow]Playlist hiện tại đang trống.[/yellow]")

    def show_accounts(self):
        accounts = self.accounts.connected_platforms()
        if not accounts:
            console.print("[yellow]Chưa có tài khoản nào. Dùng: login <ytmusic|soundcloud|spotify> <label> [token][/yellow]")
            return

        table = Table(show_header=True, header_style="bold magenta", box=box.SIMPLE)
        table.add_column("Nền tảng")
        table.add_column("Tên")
        table.add_column("Kết nối")
        table.add_column("Sync")
        for platform, account in accounts.items():
            table.add_row(
                platform,
                str(account.get("label", platform)),
                str(account.get("connected_at", "")),
                str(account.get("last_sync") or "chưa sync"),
            )
        console.print(table)

    def sync_data(self):
        snapshot = {
            "queue_count": len(self.library.queue),
            "history_count": len(self.library.history),
            "playlists": self.library.list_playlists(),
            "active_playlist": self.library.active_playlist_name,
        }
        result = self.accounts.sync(snapshot)
        console.print(
            f"[green]Đã đồng bộ local snapshot cho {result['synced_accounts']} tài khoản lúc {result['synced_at']}.[/green]"
        )

    def show_help(self):
        table = Table(show_header=True, header_style="bold green", box=box.SIMPLE)
        table.add_column("Lệnh", style="cyan", no_wrap=True)
        table.add_column("Tác dụng")
        commands = [
            ("search/s <từ khóa>", "Tìm bài, sau đó chọn phát/thêm queue/thêm playlist"),
            ("suggest/g [từ khóa]", "Gợi ý bài theo bài đang phát hoặc từ khóa"),
            ("add <số> [queue|pl] [playlist]", "Thêm kết quả search gần nhất vào queue hoặc playlist"),
            ("queue [clear|remove <số>]", "Xem, dọn hoặc xóa một bài trong queue"),
            ("playlist/pl [use <tên>|remove <số>]", "Xem/chọn/xóa trong playlist"),
            ("now/status/home", "Hiển thị dashboard Now Playing"),
            ("seek/tua <+giây|-giây|m:ss>", "Tua bài hiện tại"),
            ("next/n, back/b, stop", "Điều khiển phát nhạc"),
            ("provider <ytmusic|soundcloud|spotify>", "Đổi nguồn tìm kiếm"),
            ("login <platform> <label> [token]", "Lưu trạng thái đăng nhập local"),
            ("logout <platform>, accounts, sync", "Quản tài khoản và đồng bộ local"),
        ]
        for command, desc in commands:
            table.add_row(escape(command), desc)
        console.print(table)

    def handle_add_command(self, args: str):
        parts = args.split()
        if not parts:
            console.print("[red]Ví dụ: add 1 queue hoặc add 1 pl Favorites[/red]")
            return

        target = parts[1].lower() if len(parts) > 1 else "queue"
        playlist_name = " ".join(parts[2:]) if len(parts) > 2 else None
        if target in {"pl", "playlist"}:
            self.add_result_to_playlist(parts[0], playlist_name)
        else:
            self.add_result_to_queue(parts[0])

    def handle_playlist_command(self, args: str):
        parts = args.split(" ", 1)
        action = parts[0].lower() if parts and parts[0] else ""
        rest = parts[1] if len(parts) > 1 else ""

        if action == "use" and rest:
            self.library.set_active_playlist(rest)
            console.print(f"[green]Đã chuyển sang playlist: {self.library.active_playlist_name}[/green]")
        elif action == "remove" and rest.isdigit():
            removed = self.library.remove_from_playlist(int(rest))
            if removed:
                console.print(f"[green]Đã xóa khỏi playlist: {removed.title}[/green]")
            else:
                console.print("[red]STT playlist không hợp lệ.[/red]")
        else:
            self.show_playlist()

    def handle_login_command(self, args: str):
        parts = args.split()
        if not parts:
            console.print(f"[red]Ví dụ: login ytmusic Nelovo. Hỗ trợ: {', '.join(sorted(SUPPORTED_PLATFORMS))}[/red]")
            return

        platform = parts[0]
        label = parts[1] if len(parts) > 1 else platform
        token = " ".join(parts[2:]) if len(parts) > 2 else ""
        try:
            self.accounts.login(platform, label, token)
            console.print(f"[green]Đã lưu đăng nhập local cho {platform}.[/green]")
            console.print("[dim]OAuth/API remote thật cần credential riêng của từng nền tảng; sync hiện tại lưu snapshot local an toàn.[/dim]")
        except ValueError as e:
            console.print(f"[red]{e}[/red]")

    def run(self):
        self.show_dashboard()
        commands = [
            "search",
            "s",
            "suggest",
            "g",
            "add",
            "queue",
            "playlist",
            "pl",
            "now",
            "status",
            "home",
            "seek",
            "tua",
            "next",
            "n",
            "back",
            "b",
            "stop",
            "provider",
            "login",
            "logout",
            "accounts",
            "sync",
            "help",
            "quit",
            "exit",
            "q",
        ]
        completer = WordCompleter(commands, ignore_case=True)

        while True:
            try:
                cmd_line = self._prompt("soundtify> ", completer=completer).strip()
                if not cmd_line:
                    continue

                parts = cmd_line.split(" ", 1)
                cmd = parts[0].lower()
                args = parts[1] if len(parts) > 1 else ""

                if cmd in ["quit", "exit", "q"]:
                    self.player.stop()
                    console.print("[yellow]Tạm biệt![/yellow]")
                    sys.exit(0)
                if cmd in ["now", "status", "home"]:
                    self.show_dashboard()
                elif cmd in ["help", "?"]:
                    self.show_help()
                elif cmd == "stop":
                    self.player.stop()
                    console.print("[yellow]Đã dừng phát nhạc.[/yellow]")
                elif cmd in ["next", "n"]:
                    self.next_track()
                elif cmd in ["back", "b"]:
                    self.back_track()
                elif cmd in ["seek", "tua"]:
                    self.seek(args)
                elif cmd in ["search", "s"]:
                    self.search_and_play(args)
                elif cmd in ["suggest", "g"]:
                    self.suggest(args)
                elif cmd == "add":
                    self.handle_add_command(args)
                elif cmd == "queue":
                    self.show_queue(args)
                elif cmd in ["playlist", "pl"]:
                    self.handle_playlist_command(args)
                elif cmd == "provider":
                    provider_name = args.strip().lower()
                    if provider_name in self.providers:
                        self.current_provider = self.providers[provider_name]
                        self.provider_name = provider_name
                        self.show_dashboard()
                    else:
                        console.print(f"[red]Provider không hợp lệ. Hỗ trợ: {', '.join(self.providers.keys())}[/red]")
                elif cmd == "login":
                    self.handle_login_command(args)
                elif cmd == "logout":
                    if self.accounts.logout(args):
                        console.print(f"[green]Đã đăng xuất {args}.[/green]")
                    else:
                        console.print("[yellow]Không tìm thấy tài khoản này.[/yellow]")
                elif cmd == "accounts":
                    self.show_accounts()
                elif cmd == "sync":
                    self.sync_data()
                else:
                    self.search_and_play(cmd_line)
            except KeyboardInterrupt:
                continue
            except EOFError:
                self.player.stop()
                break
