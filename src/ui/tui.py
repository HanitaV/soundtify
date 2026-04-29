import subprocess
import threading
import webbrowser
from typing import Iterable
from urllib.parse import parse_qs, urlparse

from textual.app import App, ComposeResult
from textual.containers import Horizontal, HorizontalScroll, Vertical, VerticalScroll
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, ProgressBar, Static

from src.core.accounts import AccountManager, SUPPORTED_PLATFORMS
from src.core.library import LibraryManager
from src.core.oauth import DEFAULT_REDIRECT_URI, OAuthCallbackServer, OAuthSetupServer
from src.core.player import Player
from src.core.security import secure_load_json, secure_save_json
from src.providers import SoundCloudProvider, SpotifyProvider, YTMusicProvider
from src.providers.base import Track, format_duration, parse_duration


CACHE_FILE = "search_cache.json"
MAX_CACHE_ENTRIES = 50


class SoundtifyTUI(App):
    CSS = """
    Screen {
        background: #101010;
        color: #f4f4f4;
    }

    #root {
        height: 1fr;
        min-height: 0;
    }

    #sidebar {
        width: 31;
        min-width: 24;
        background: #171717;
        border-right: solid #2a2a2a;
        padding: 1;
    }

    #brand {
        height: 3;
        color: #ff5500;
        text-style: bold;
        content-align: center middle;
    }

    #main {
        width: 1fr;
        min-width: 42;
        padding: 1;
    }

    #search_row {
        height: 3;
    }

    #search_input {
        width: 1fr;
        margin-right: 1;
    }

    #hero {
        height: 5;
        margin: 1 0;
        padding: 1;
        background: #202020;
        border: solid #333333;
        color: #f4f4f4;
    }

    #tips {
        height: 4;
        margin-bottom: 1;
        padding: 1;
        background: #161616;
        border: solid #2b2b2b;
        color: #c9c9c9;
    }

    #feed_header {
        height: 2;
        color: #ff8a3d;
        text-style: bold;
    }

    DataTable {
        height: 1fr;
        background: #121212;
        border: solid #303030;
    }

    #player {
        height: 10;
        background: #181818;
        border-top: solid #303030;
        padding: 1;
    }

    #player_status {
        height: 3;
    }

    #player_controls {
        height: 4;
    }

    #track_info {
        width: 1fr;
        min-width: 22;
    }

    #time_info {
        width: 18;
        content-align: center middle;
        color: #d6d6d6;
    }

    #progress {
        width: 24;
        margin: 1 2 0 0;
    }

    Button {
        margin: 0 1 1 0;
        min-width: 10;
        height: 3;
        min-height: 3;
    }

    Button.primary {
        background: #ff5500;
        color: #ffffff;
    }

    Button.sidebar {
        width: 100%;
        height: 3;
        min-height: 3;
    }

    .muted {
        color: #9b9b9b;
    }

    Screen.compact #main {
        min-width: 30;
        padding: 0 1;
    }

    Screen.compact #sidebar {
        width: 28;
        min-width: 24;
        padding: 0 1;
    }

    Screen.compact #hero {
        display: none;
    }

    Screen.compact #tips {
        display: none;
    }

    Screen.compact #player {
        height: 8;
    }

    Screen.compact #progress {
        width: 14;
    }

    Screen.compact #time_info {
        width: 13;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "home", "Home"),
        ("space", "play_selected", "Play"),
        ("p", "toggle_playback", "Play/Stop"),
        ("j", "rewind_15", "-15s"),
        ("k", "forward_15", "+15s"),
        ("n", "next_track", "Next"),
        ("b", "back_track", "Back"),
        ("s", "focus_search", "Search"),
    ]

    def __init__(self):
        super().__init__()
        self.player = Player()
        self.providers = {
            "ytmusic": YTMusicProvider(),
            "soundcloud": SoundCloudProvider(),
            "spotify": SpotifyProvider(),
        }
        self.provider_name = "ytmusic"
        self.current_provider = self.providers[self.provider_name]
        self.library = LibraryManager()
        self.accounts = AccountManager()
        self.search_cache = secure_load_json(CACHE_FILE)
        if not isinstance(self.search_cache, dict):
            self.search_cache = {}

        self.visible_tracks: list[Track] = []
        self.selected_track: Track | None = None
        self.selected_account_provider = self.provider_name
        self.current_track: Track | None = None
        self.feed_title = "Home recommendations"
        self.current_view = "home"
        self.oauth_server: OAuthCallbackServer | None = None
        self.oauth_setup_server: OAuthSetupServer | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="root"):
            with VerticalScroll(id="sidebar"):
                yield Static("SOUNDTIFY", id="brand")
                yield Button("Home", id="home_btn", classes="sidebar primary")
                yield Button("Trending", id="trending_btn", classes="sidebar")
                yield Button("Recent", id="recent_btn", classes="sidebar")
                yield Button("Playlist", id="playlist_btn", classes="sidebar")
                yield Button("Account Manager", id="accounts_btn", classes="sidebar")
                yield Button("Help", id="help_btn", classes="sidebar")
                yield Static("", classes="muted")
                yield Label("Provider")
                yield Button("YouTube Music", id="provider_ytmusic", classes="sidebar")
                yield Button("SoundCloud", id="provider_soundcloud", classes="sidebar")
                yield Button("Spotify via YT", id="provider_spotify", classes="sidebar")
                yield Static("", classes="muted")
                yield Button("Connect provider", id="connect_btn", classes="sidebar")
                yield Button("Sync library", id="sync_btn", classes="sidebar")
                yield Button("Logout provider", id="logout_btn", classes="sidebar")
            with Vertical(id="main"):
                with Horizontal(id="search_row"):
                    yield Input(placeholder="Search tracks, artists, mixes...", id="search_input")
                    yield Button("Search", id="search_btn", classes="primary")
                yield Static(id="hero")
                yield Static(id="tips")
                yield Static(id="feed_header")
                yield DataTable(id="track_table", cursor_type="row")
        with Vertical(id="player"):
            with Horizontal(id="player_status"):
                yield Static(id="track_info")
                yield ProgressBar(total=100, show_eta=False, id="progress")
                yield Static(id="time_info")
            with HorizontalScroll(id="player_controls"):
                yield Button("Back", id="back_btn")
                yield Button("-15s", id="rewind_btn")
                yield Button("Play", id="play_btn", classes="primary")
                yield Button("+15s", id="forward_btn")
                yield Button("Next", id="next_btn")
                yield Button("Add", id="add_btn")
                yield Button("Share URL", id="share_btn")
                yield Button("Stop", id="stop_btn")
        yield Footer()

    def on_unmount(self) -> None:
        self.shutdown_audio()

    def action_quit(self) -> None:
        self.shutdown_audio()
        self.exit()

    def shutdown_audio(self) -> None:
        self.player.stop()
        self.close_oauth_server()
        self.close_oauth_setup_server()

    def on_mount(self) -> None:
        self.update_compact_mode()
        table = self.query_one("#track_table", DataTable)
        table.add_columns("#", "Title", "Artist", "Source", "Duration")
        self.set_interval(1, self.refresh_player)
        self.action_home()

    def on_resize(self, event) -> None:
        self.update_compact_mode()

    def update_compact_mode(self) -> None:
        size = self.size
        self.screen.set_class(size.width < 100 or size.height < 30, "compact")

    def action_home(self) -> None:
        self.feed_title = "Home recommendations"
        self.update_static_panels()
        immediate_tracks = self.local_home_tracks()
        if immediate_tracks:
            self.set_tracks(immediate_tracks, "Home recommendations")
        else:
            self.set_loading("Loading recommendations...")
        self.load_tracks_async("top hits vietnam", "Recommended for you")

    def action_focus_search(self) -> None:
        self.query_one("#search_input", Input).focus()

    def action_play_selected(self) -> None:
        if self.selected_track:
            self.play_track_async(self.selected_track)
        elif self.visible_tracks:
            self.selected_track = self.visible_tracks[0]
            self.play_track_async(self.selected_track)

    def action_toggle_playback(self) -> None:
        self.toggle_playback()

    def action_rewind_15(self) -> None:
        self.seek_relative(-15)

    def action_forward_15(self) -> None:
        self.seek_relative(15)

    def action_next_track(self) -> None:
        self.next_track()

    def action_back_track(self) -> None:
        self.back_track()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "home_btn":
            self.action_home()
        elif button_id == "trending_btn":
            self.set_loading("Loading trending tracks...")
            self.load_tracks_async("trending music", "Trending now")
        elif button_id == "recent_btn":
            self.set_tracks(self.library.history, "Recently played")
        elif button_id == "playlist_btn":
            self.set_tracks(self.library.active_playlist, f"Playlist: {self.library.active_playlist_name}")
        elif button_id == "accounts_btn":
            self.show_account_manager()
        elif button_id == "help_btn":
            self.show_help()
        elif button_id.startswith("provider_"):
            provider_name = button_id.removeprefix("provider_")
            self.set_provider(provider_name)
            if self.current_view in {"accounts", "account_actions"}:
                self.show_account_actions(provider_name)
        elif button_id == "connect_btn":
            self.connect_current_provider()
        elif button_id == "sync_btn":
            self.sync_library()
        elif button_id == "logout_btn":
            self.logout_current_provider()
        elif button_id == "search_btn":
            self.run_search()
        elif button_id == "play_btn":
            self.toggle_playback()
        elif button_id == "next_btn":
            self.next_track()
        elif button_id == "back_btn":
            self.back_track()
        elif button_id == "rewind_btn":
            self.seek_relative(-15)
        elif button_id == "forward_btn":
            self.seek_relative(15)
        elif button_id == "stop_btn":
            self.player.stop()
            self.refresh_player()
        elif button_id == "add_btn":
            self.add_selected_to_playlist()
        elif button_id == "share_btn":
            self.share_current_url()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search_input":
            self.run_search()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self.select_row_key(event.row_key.value)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row_key = event.row_key.value
        if self.current_view == "accounts":
            provider = self.provider_from_account_key(row_key)
            if provider:
                self.show_account_actions(provider)
            return
        if self.current_view == "account_actions":
            self.handle_account_action(row_key)
            return

        self.select_row_key(row_key)
        if self.current_view == "accounts":
            return
        self.action_play_selected()

    def set_provider(self, provider_name: str) -> None:
        if provider_name not in self.providers:
            self.notify(f"Unsupported provider: {provider_name}", severity="error")
            return
        self.provider_name = provider_name
        self.current_provider = self.providers[provider_name]
        self.update_static_panels()
        self.notify(f"Search provider: {provider_name}")

    def run_search(self) -> None:
        query = self.query_one("#search_input", Input).value.strip()
        if not query:
            self.notify("Type a song, artist, or mood first.", severity="warning")
            return

        cached = self.get_cached_results(query)
        if cached:
            self.set_tracks(cached, f"Search: {query}")
            return

        self.set_loading(f"Searching {self.provider_name}: {query}")
        self.load_tracks_async(query, f"Search: {query}", cache_query=query)

    def local_home_tracks(self) -> list[Track]:
        tracks = self.library.history[:6] + self.library.active_playlist[:6] + self.library.queue[:6]
        if tracks:
            return self.unique_tracks(tracks)[:12]

        cached_tracks: list[Track] = []
        for items in self.search_cache.values():
            if isinstance(items, list):
                cached_tracks.extend(Track.from_dict(item) for item in items if isinstance(item, dict))
        return self.unique_tracks(cached_tracks)[:12]

    def load_tracks_async(self, query: str, title: str, cache_query: str | None = None) -> None:
        provider = self.current_provider

        def worker() -> None:
            try:
                tracks = provider.search(query)
                if cache_query:
                    self.save_cached_results(cache_query, tracks)
                self.call_from_thread(self.set_tracks, tracks, title)
            except Exception as exc:
                message = f"Search failed: {exc}"
                self.call_from_thread(lambda message=message: self.notify(message, severity="error"))

        threading.Thread(target=worker, daemon=True).start()

    def play_track_async(self, track: Track) -> None:
        self.selected_track = track
        self.notify(f"Opening stream: {track.title}")

        def worker() -> None:
            provider_name, provider = self.provider_for_track(track)
            try:
                url = provider.get_stream_url(track.id)
                ok = self.player.play(url, 0, parse_duration(track.duration))
                self.call_from_thread(self.on_play_started, ok, track, provider_name)
            except Exception as exc:
                message = f"Could not play track: {exc}"
                self.call_from_thread(lambda message=message: self.notify(message, severity="error"))

        threading.Thread(target=worker, daemon=True).start()

    def on_play_started(self, ok: bool, track: Track, provider_name: str) -> None:
        if not ok:
            self.notify("Player could not start.", severity="error")
            return
        self.current_track = track
        self.provider_name = provider_name
        self.current_provider = self.providers[provider_name]
        self.library.add_to_history(track)
        self.refresh_player()
        self.update_static_panels()
        self.notify(f"Now playing: {track.title}")

    def next_track(self) -> None:
        next_item = self.library.pop_next_queue()
        if next_item:
            self.play_track_async(next_item)
            return

        playlist = self.library.active_playlist
        if not playlist:
            self.notify("Queue and playlist are empty.", severity="warning")
            return
        if not self.current_track:
            self.play_track_async(playlist[0])
            return
        current_index = next((idx for idx, item in enumerate(playlist) if item.id == self.current_track.id), -1)
        self.play_track_async(playlist[(current_index + 1) % len(playlist)])

    def back_track(self) -> None:
        history = self.library.history
        if len(history) < 2:
            self.notify("No previous track yet.", severity="warning")
            return
        self.play_track_async(history[1])

    def add_selected_to_playlist(self) -> None:
        track = self.selected_track or self.current_track
        if not track:
            self.notify("Select a track first.", severity="warning")
            return
        playlist_name = self.library.add_to_playlist(track)
        self.notify(f"Added to {playlist_name}: {track.title}")
        self.update_static_panels()

    def share_current_url(self) -> None:
        track = self.current_track or self.selected_track
        if not track:
            self.notify("Select or play a track first.", severity="warning")
            return
        url = self.share_url_for(track)
        if self.copy_to_clipboard(url):
            self.notify("Share URL copied to clipboard.")
        else:
            self.notify(url, title="Share URL", timeout=8)

    def seek_relative(self, seconds: int) -> None:
        if not self.current_track:
            self.notify("Play a track before seeking.", severity="warning")
            return
        if self.player.seek_relative(seconds):
            self.refresh_player()
            self.notify(f"Jumped to {format_duration(self.player.elapsed_seconds())}.")
        else:
            self.notify("Could not seek this stream.", severity="error")

    def toggle_playback(self) -> None:
        if self.player.is_playing():
            elapsed = self.player.elapsed_seconds()
            self.player.stop()
            self.player.offset_seconds = elapsed
            self.refresh_player()
            self.notify(f"Stopped at {format_duration(elapsed)}. Press P to resume.")
            return

        if self.current_track and self.player.stream_url:
            if self.player.seek_to(self.player.offset_seconds):
                self.refresh_player()
                self.notify("Playback resumed.")
            else:
                self.notify("Could not resume this stream.", severity="error")
            return

        self.action_play_selected()

    def refresh_player(self) -> None:
        track_info = self.query_one("#track_info", Static)
        time_info = self.query_one("#time_info", Static)
        progress = self.query_one("#progress", ProgressBar)

        if not self.current_track:
            track_info.update("[b]Nothing playing[/b]\n[dim]Click a track, then Play.[/dim]")
            time_info.update("0:00 / 0:00")
            progress.update(progress=0)
            return

        elapsed = self.player.elapsed_seconds()
        total = parse_duration(self.current_track.duration)
        percent = int((elapsed / total) * 100) if total else 0
        state = "Playing" if self.player.is_playing() else "Stopped"
        track_info.update(
            f"[b]{self.current_track.title}[/b]\n"
            f"[dim]{self.current_track.artist} - {self.current_track.source} - {state}[/dim]"
        )
        time_info.update(f"{format_duration(elapsed)} / {self.current_track.duration}")
        progress.update(progress=max(0, min(100, percent)))

    def update_static_panels(self) -> None:
        connected = ", ".join(self.accounts.connected_platforms().keys()) or "No accounts"
        hero = (
            "[b]Home[/b]\n"
            "Start with recommendations, search anything, click a row, then use Play/Add/Share.\n"
            f"[dim]Provider: {self.provider_name} | Playlist: {self.library.active_playlist_name} | {connected}[/dim]"
        )
        tips = (
            "[b]Quick help for beginners[/b]\n"
            "1. Search a song or click Trending.  2. Click a row.  3. Press Play.  "
            "Use Add to save, Share URL to copy a link, Next for the queue."
        )
        self.query_one("#hero", Static).update(hero)
        self.query_one("#tips", Static).update(tips)

    def set_loading(self, message: str) -> None:
        self.current_view = "tracks"
        self.query_one("#feed_header", Static).update(message)
        table = self.query_one("#track_table", DataTable)
        table.clear()
        table.add_row("...", message, "Please wait", self.provider_name, "", key="loading")

    def set_tracks(self, tracks: Iterable[Track], title: str) -> None:
        self.current_view = "tracks"
        self.visible_tracks = list(tracks)
        self.selected_track = self.visible_tracks[0] if self.visible_tracks else None
        self.query_one("#feed_header", Static).update(title)
        table = self.query_one("#track_table", DataTable)
        table.clear()
        if not self.visible_tracks:
            table.add_row("-", "No tracks found", "Try another search", self.provider_name, "", key="empty")
            return
        for idx, track in enumerate(self.visible_tracks, start=1):
            table.add_row(str(idx), track.title, track.artist, track.source, track.duration, key=str(idx - 1))

    def select_row_key(self, row_key) -> None:
        if row_key is None:
            return

        try:
            index = int(row_key)
        except (TypeError, ValueError):
            return
        if 0 <= index < len(self.visible_tracks):
            self.selected_track = self.visible_tracks[index]

    def show_account_manager(self) -> None:
        self.current_view = "accounts"
        accounts = self.accounts.connected_platforms()
        pending = self.accounts.data.get("oauth_pending", {})
        self.query_one("#feed_header", Static).update("Account Manager")
        self.query_one("#hero", Static).update(
            "[b]Account Manager[/b]\n"
            "Choose a provider on the left, then click Connect provider. "
            "Soundtify will open the browser and try to capture the OAuth callback automatically."
        )
        self.query_one("#tips", Static).update(
            "[b]GUI login[/b]\n"
            "For SoundCloud, Spotify, and Google, set client credentials first. "
            "If browser callback fails, paste the callback URL/code into Search and click Connect again."
        )
        table = self.query_one("#track_table", DataTable)
        table.clear(columns=True)
        table.add_columns("Platform", "Status", "Label", "Last sync", "Token", "Action")
        for platform in sorted(SUPPORTED_PLATFORMS):
            account = accounts.get(platform, {})
            is_connected = isinstance(account, dict) and bool(account)
            is_pending = isinstance(pending.get(platform), dict)
            status = "Connected" if is_connected else "Waiting for callback" if is_pending else "Not connected"
            token_state = "Access token saved" if account.get("access_token") else "No token"
            table.add_row(
                platform,
                status,
                str(account.get("label", "-")),
                str(account.get("last_sync") or "-"),
                token_state,
                "Select provider, then Connect/Sync/Logout",
                key=f"account:{platform}",
            )
        self.selected_account_provider = self.provider_name

    def provider_from_account_key(self, row_key) -> str:
        if row_key is None:
            return ""
        key = str(row_key)
        if key.startswith("account:"):
            provider = key.split(":", 1)[1]
            return provider if provider in SUPPORTED_PLATFORMS else ""
        return ""

    def show_account_actions(self, provider: str) -> None:
        if provider not in SUPPORTED_PLATFORMS:
            return
        self.current_view = "account_actions"
        self.selected_account_provider = provider
        self.provider_name = provider
        self.current_provider = self.providers[provider]
        account = self.accounts.connected_platforms().get(provider, {})
        pending = self.accounts.pending_oauth(provider)
        status = "connected" if account else "waiting for callback" if pending else "not connected"

        self.query_one("#feed_header", Static).update(f"Account actions: {provider}")
        self.query_one("#hero", Static).update(
            f"[b]{provider} account[/b]\n"
            f"Status: {status}. Choose an action below with Enter or mouse."
        )
        self.query_one("#tips", Static).update(
            "[b]Guide[/b]\n"
            "Connect opens the browser and listens for local callback. "
            "If callback fails, paste callback URL/code into Search then choose Connect again."
        )

        table = self.query_one("#track_table", DataTable)
        table.clear(columns=True)
        table.add_columns("Action", "What it does", "When to use")
        table.add_row("Login / Connect", "Open browser OAuth flow and auto-capture callback", "First setup or token expired", key="action:connect")
        table.add_row("Sync now", "Save current queue/history/playlist snapshot to this account record", "After changing playlist/queue", key="action:sync")
        table.add_row("Disconnect", "Remove saved token/account for this provider", "When switching account", key="action:logout")
        table.add_row("Setup guide", "Show client ID, redirect URI, SoundCloud notes", "If Connect fails", key="action:guide")
        table.add_row("Back to Account Manager", "Return to account list", "Review all linked accounts", key="action:back")

    def handle_account_action(self, row_key) -> None:
        key = "" if row_key is None else str(row_key)
        if not key.startswith("action:"):
            return
        action = key.split(":", 1)[1]
        provider = self.selected_account_provider
        self.provider_name = provider
        self.current_provider = self.providers[provider]

        if action == "connect":
            self.connect_current_provider()
        elif action == "sync":
            self.sync_library()
        elif action == "logout":
            self.logout_current_provider()
        elif action == "guide":
            self.show_account_setup_guide(provider)
        elif action == "back":
            self.show_account_manager()

    def show_account_setup_guide(self, provider: str) -> None:
        self.current_view = "account_actions"
        prefix = "GOOGLE" if provider == "ytmusic" else provider.upper()
        redirect = DEFAULT_REDIRECT_URI
        setup_url = self.open_oauth_setup(provider)
        self.query_one("#feed_header", Static).update(f"Setup guide: {provider}")
        self.query_one("#hero", Static).update(
            f"[b]{provider} setup[/b]\n"
            f"Opened local setup page: {setup_url}"
        )
        self.query_one("#tips", Static).update(
            "[b]SoundCloud note[/b]\n"
            "SoundCloud OAuth token exchange requires both client_id and client_secret. "
            "Fill the browser form, save it, then return here and choose Login / Connect."
        )
        table = self.query_one("#track_table", DataTable)
        table.clear(columns=True)
        table.add_columns("Setting", "Value")
        table.add_row("Local setup URL", setup_url, key="guide:url")
        table.add_row("Redirect URI", redirect, key="guide:redirect")
        table.add_row("Client ID env var", f"SOUNDTIFY_{prefix}_CLIENT_ID", key="guide:client_id")
        table.add_row("Client secret env var", f"SOUNDTIFY_{prefix}_CLIENT_SECRET", key="guide:client_secret")
        table.add_row("Config file", "auth_config.json in Soundtify app data, written by the browser form", key="guide:file")
        table.add_row("Back", "Press Enter to return to action menu", key="action:back")

    def open_oauth_setup(self, provider: str) -> str:
        try:
            if self.oauth_setup_server is None:
                self.oauth_setup_server = OAuthSetupServer()
            base_url = self.oauth_setup_server.start()
            setup_url = f"{base_url}/?provider={provider}"
            self.copy_to_clipboard(setup_url)
            try:
                webbrowser.open(setup_url)
            except Exception:
                pass
            return setup_url
        except Exception as exc:
            self.notify(f"Setup server failed: {exc}", severity="error", timeout=8)
            return "Không mở được setup server."

    def connect_current_provider(self) -> None:
        value = self.query_one("#search_input", Input).value.strip()
        code, state = self.extract_auth_callback(value)
        pending = self.accounts.pending_oauth(self.provider_name)
        if code and pending:
            expected_state = pending.get("state")
            if state and expected_state and state != expected_state:
                self.notify("OAuth state mismatch. Click Connect again to start over.", severity="error")
                return
            try:
                self.accounts.finish_oauth(self.provider_name, code)
                self.update_static_panels()
                self.notify(f"{self.provider_name} OAuth connected.")
                if self.current_view == "accounts":
                    self.show_account_manager()
            except Exception as exc:
                self.notify(f"OAuth finish failed: {exc}", severity="error", timeout=8)
            return

        try:
            url = self.accounts.start_oauth(self.provider_name)
            pending = self.accounts.pending_oauth(self.provider_name)
            if pending:
                self.start_oauth_callback_waiter(self.provider_name, pending)
            copied = self.copy_to_clipboard(url)
            try:
                webbrowser.open(url)
            except Exception:
                pass
            self.update_static_panels()
            note = "Link copied. " if copied else ""
            self.notify(
                f"{note}Login opened. Paste callback URL or code into Search, then click Connect again.",
                timeout=10,
            )
        except Exception as exc:
            self.notify(f"OAuth start failed: {exc}", severity="error", timeout=10)
        if self.current_view == "accounts":
            self.show_account_manager()

    def logout_current_provider(self) -> None:
        if self.accounts.logout(self.provider_name):
            self.notify(f"Logged out {self.provider_name}.")
        else:
            self.notify(f"{self.provider_name} is not connected.", severity="warning")
        self.update_static_panels()
        if self.current_view == "accounts":
            self.show_account_manager()

    def sync_library(self) -> None:
        snapshot = {
            "queue_count": len(self.library.queue),
            "history_count": len(self.library.history),
            "playlists": self.library.list_playlists(),
            "active_playlist": self.library.active_playlist_name,
        }
        result = self.accounts.sync(snapshot)
        self.update_static_panels()
        self.notify(f"Synced {result['synced_accounts']} account(s).")
        if self.current_view == "accounts":
            self.show_account_manager()

    def start_oauth_callback_waiter(self, platform: str, pending: dict) -> None:
        self.close_oauth_server()
        try:
            server = OAuthCallbackServer(pending["redirect_uri"])
            server.start()
        except Exception as exc:
            self.notify(f"GUI callback unavailable: {exc}. Paste callback URL/code manually.", severity="warning", timeout=10)
            return

        self.oauth_server = server

        def worker() -> None:
            try:
                code, state = server.wait()
                expected_state = pending.get("state")
                if state and expected_state and state != expected_state:
                    raise RuntimeError("OAuth state mismatch.")
                self.accounts.finish_oauth(platform, code)
                self.call_from_thread(self.on_oauth_connected, platform)
            except Exception as exc:
                message = f"OAuth callback failed: {exc}. You can paste the callback URL/code manually."
                self.call_from_thread(lambda message=message: self.notify(message, severity="warning", timeout=10))
            finally:
                server.close()
                if self.oauth_server is server:
                    self.oauth_server = None

        threading.Thread(target=worker, daemon=True).start()

    def on_oauth_connected(self, platform: str) -> None:
        self.update_static_panels()
        self.notify(f"{platform} connected via browser callback.")
        if self.current_view == "accounts":
            self.show_account_manager()

    def close_oauth_server(self) -> None:
        if self.oauth_server:
            self.oauth_server.close()
            self.oauth_server = None

    def close_oauth_setup_server(self) -> None:
        if self.oauth_setup_server:
            self.oauth_setup_server.close()
            self.oauth_setup_server = None

    def show_help(self) -> None:
        help_tracks = [
            Track("help1", "Search bar", "Type a song, artist, or mood. Press Enter or click Search.", "Help", ""),
            Track("help2", "Mouse controls", "Click a row to select it. Double click/Enter row or press Play.", "Help", ""),
            Track("help3", "Save music", "Click Add to save the selected/current track to your playlist.", "Help", ""),
            Track("help4", "Share", "Click Share URL to copy a public music URL.", "Help", ""),
            Track("help5", "Keyboard", "P play/stop, J -15s, K +15s, N next, B back, S search, R home, Q quit.", "Help", ""),
        ]
        self.set_tracks(help_tracks, "How to use Soundtify")

    def get_cached_results(self, query: str) -> list[Track] | None:
        key = f"{self.provider_name}:{query.strip().casefold()}"
        raw_tracks = self.search_cache.get(key)
        if not isinstance(raw_tracks, list):
            return None
        tracks = [Track.from_dict(item) for item in raw_tracks if isinstance(item, dict)]
        return tracks or None

    def save_cached_results(self, query: str, tracks: list[Track]) -> None:
        key = f"{self.provider_name}:{query.strip().casefold()}"
        self.search_cache[key] = [track.to_dict() for track in tracks]
        while len(self.search_cache) > MAX_CACHE_ENTRIES:
            oldest_key = next(iter(self.search_cache))
            self.search_cache.pop(oldest_key, None)
        secure_save_json(CACHE_FILE, self.search_cache)

    def provider_for_track(self, track: Track):
        source = track.source.lower()
        if "soundcloud" in source:
            return "soundcloud", self.providers["soundcloud"]
        if "spotify" in source:
            return "spotify", self.providers["spotify"]
        return "ytmusic", self.providers["ytmusic"]

    def share_url_for(self, track: Track) -> str:
        source = track.source.lower()
        if "soundcloud" in source and track.id.startswith("http"):
            return track.id
        return f"https://music.youtube.com/watch?v={track.id}"

    def copy_to_clipboard(self, text: str) -> bool:
        try:
            subprocess.run("clip", input=text, text=True, check=True, shell=True)
            return True
        except Exception:
            return False

    def extract_auth_callback(self, value: str) -> tuple[str, str]:
        if not value:
            return "", ""
        if value.startswith("http://") or value.startswith("https://"):
            params = parse_qs(urlparse(value).query)
            return (params.get("code") or [""])[0], (params.get("state") or [""])[0]
        if "code=" in value:
            params = parse_qs(value.partition("?")[2] or value)
            return (params.get("code") or [""])[0], (params.get("state") or [""])[0]
        return value.strip(), ""

    def unique_tracks(self, tracks: list[Track]) -> list[Track]:
        seen = set()
        result = []
        for track in tracks:
            key = (track.source, track.id)
            if key in seen:
                continue
            seen.add(key)
            result.append(track)
        return result
