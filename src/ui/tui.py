import subprocess
import threading
import webbrowser
from typing import Iterable
from urllib.parse import parse_qs, urlparse

from textual.app import App, ComposeResult
from textual.containers import Horizontal, HorizontalScroll, Vertical, VerticalScroll
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, ProgressBar, Static

from src.core import debug_log
from src.core.accounts import AccountManager, SUPPORTED_PLATFORMS
from src.core.downloads import DownloadManager
from src.core.library import LibraryManager
from src.core.oauth import DEFAULT_REDIRECT_URI, OAuthCallbackServer, OAuthSetupServer
from src.core.player import Player
from src.core.presence import PresenceManager
from src.core.security import secure_load_json, secure_save_json
from src.core.soundcloud_auth import extract_soundcloud_token
from src.core.sponsorblock import SponsorSegment, fetch_segments as fetch_sponsor_segments
from src.core.ytmusic_auth import extract_cookie_from_input
from src.providers import SoundCloudProvider, SpotifyProvider, YTMusicProvider
from src.providers.ytmusic import ArtistChannel
from src.providers.base import LyricLine, Track, format_duration, parse_duration


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

    #seek_row {
        height: 3;
    }

    #seek_input {
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

    .hidden {
        display: none;
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
        ("ctrl+a", "select_all_text", "Select all"),
        ("tab", "focus_next", "Next box"),
        ("shift+tab", "focus_previous", "Prev box"),
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
        self.downloads = DownloadManager()
        self.accounts = AccountManager()
        self.presence = PresenceManager()
        self.search_cache = secure_load_json(CACHE_FILE)
        if not isinstance(self.search_cache, dict):
            self.search_cache = {}

        self.visible_tracks: list[Track] = []
        self.visible_artists: list[ArtistChannel] = []
        self.lyric_lines: list[LyricLine] = []
        self.lyric_track_key = ""
        self.lyrics_loaded = False
        self.lyrics_error = ""
        self.home_lyrics_enabled = True
        self.home_lyrics_last_index = -1
        self.suggested_next_tracks: list[Track] = []
        self.home_recommendation_tracks: list[Track] = []
        self.search_suggestions: list[tuple[str, str]] = []
        self.selected_track: Track | None = None
        self.selected_artist: ArtistChannel | None = None
        self.selected_account_provider = self.provider_name
        self.current_track: Track | None = None
        self.next_suggestions_track_key = ""
        self.next_suggestions_loaded = False
        self.sponsor_segments: list[SponsorSegment] = []
        self.sponsor_track_key = ""
        self.sponsor_skip_until = 0.0
        self.playback_recovering = False
        self.playback_retries = 0
        self.autoplay_in_progress = False
        self.recommendation_request_id = 0
        self.suggestion_request_id = 0
        self.suppress_suggestions = False
        self.feed_title = "Home"
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
                yield Button("Downloads", id="downloads_btn", classes="sidebar")
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
                    yield Button("Clear", id="clear_search_btn")
                    yield Button("Artists", id="artist_search_btn")
                    yield Button("Search", id="search_btn", classes="primary")
                with Horizontal(id="seek_row", classes="hidden"):
                    yield Input(placeholder="Seek to 83, 1:23, or 01:02:03...", id="seek_input")
                    yield Button("Go", id="seek_go_btn", classes="primary")
                    yield Button("Cancel", id="seek_cancel_btn")
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
                yield Button("Seek", id="seek_btn")
                yield Button("Lyrics On", id="lyrics_toggle_btn")
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
        self.presence.close()
        self.close_oauth_server()
        self.close_oauth_setup_server()

    def on_mount(self) -> None:
        self.update_compact_mode()
        self.prepare_track_table()
        self.set_interval(1, self.refresh_player)
        self.downloads.cleanup()
        self.action_home()

    def on_resize(self, event) -> None:
        self.update_compact_mode()

    def update_compact_mode(self) -> None:
        size = self.size
        self.screen.set_class(size.width < 100 or size.height < 30, "compact")

    def action_home(self) -> None:
        self.feed_title = "Home"
        self.update_static_panels()
        if not self.home_recommendation_tracks:
            self.home_recommendation_tracks = self.local_home_tracks()
        self.show_home()
        self.load_home_recommendations_async()

    def action_focus_search(self) -> None:
        self.query_one("#search_input", Input).focus()

    def action_select_all_text(self) -> None:
        focused = self.focused
        if isinstance(focused, Input):
            focused.select_all()
            return
        search = self.query_one("#search_input", Input)
        search.focus()
        search.select_all()

    def clear_search_bar(self, notify: bool = True) -> None:
        search = self.query_one("#search_input", Input)
        search.value = ""
        search.focus()
        if notify:
            self.notify("Search cleared.")

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

    def toggle_home_lyrics(self) -> None:
        self.home_lyrics_enabled = not self.home_lyrics_enabled
        self.home_lyrics_last_index = -1
        self.update_lyrics_toggle_button()
        if self.home_lyrics_enabled and self.current_track and self.lyric_track_key != self.downloads.track_key(self.current_track):
            self.load_lyrics_async(self.current_track)
        if self.current_view == "home":
            self.show_home()
        self.notify(f"Home lyrics {'shown' if self.home_lyrics_enabled else 'hidden'}.")

    def update_lyrics_toggle_button(self) -> None:
        try:
            self.query_one("#lyrics_toggle_btn", Button).label = "Lyrics On" if self.home_lyrics_enabled else "Lyrics Off"
        except Exception:
            pass

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
        elif button_id == "downloads_btn":
            self.show_download_manager()
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
        elif button_id == "artist_search_btn":
            self.run_artist_search()
        elif button_id == "clear_search_btn":
            self.clear_search_bar()
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
        elif button_id == "seek_btn":
            self.show_seek_input()
        elif button_id == "lyrics_toggle_btn":
            self.toggle_home_lyrics()
        elif button_id == "seek_go_btn":
            self.seek_from_prompt()
        elif button_id == "seek_cancel_btn":
            self.hide_seek_input()
        elif button_id == "stop_btn":
            self.player.stop()
            self.update_presence_for_current(playing=False)
            self.refresh_player()
        elif button_id == "add_btn":
            self.add_selected_to_playlist()
        elif button_id == "share_btn":
            self.share_current_url()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search_input":
            self.run_search()
        elif event.input.id == "seek_input":
            self.seek_from_prompt()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search_input" and not self.suppress_suggestions:
            self.update_search_suggestions(event.value)

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
        if self.current_view == "downloads":
            self.handle_download_action(row_key)
            return
        if self.current_view == "artist_results":
            self.open_artist_from_key(row_key)
            return
        if self.current_view == "artist_tabs":
            self.handle_artist_tab(row_key)
            return
        if self.current_view == "suggestions":
            self.apply_search_suggestion(row_key)
            return
        key_text = "" if row_key is None else str(row_key)
        if key_text.startswith("lyrics:"):
            self.handle_lyric_row(row_key)
            return
        if not key_text.isdigit():
            return
        self.select_row_key(row_key)
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
        self.suggestion_request_id += 1

        cached = self.get_cached_results(query)
        if cached:
            self.set_tracks(cached, f"Search: {query}")
            return

        self.set_loading(f"Searching {self.provider_name}: {query}")
        self.load_tracks_async(query, f"Search: {query}", cache_query=query)

    def run_artist_search(self) -> None:
        query = self.query_one("#search_input", Input).value.strip()
        if not query:
            self.notify("Type an artist or channel name first.", severity="warning")
            return
        self.suggestion_request_id += 1
        self.provider_name = "ytmusic"
        self.current_provider = self.providers["ytmusic"]
        self.set_artist_loading(f"Searching artists/channels: {query}")
        self.load_artists_async(query)

    def local_home_tracks(self) -> list[Track]:
        tracks = self.library.history[:6] + self.library.active_playlist[:6]
        if tracks:
            return self.unique_tracks(tracks)[:12]

        cached_tracks: list[Track] = []
        for items in self.search_cache.values():
            if isinstance(items, list):
                cached_tracks.extend(Track.from_dict(item) for item in items if isinstance(item, dict))
        return self.unique_tracks(cached_tracks)[:12]

    def load_home_recommendations_async(self) -> None:
        provider = self.current_provider
        title = "Recommended for you"

        def worker() -> None:
            try:
                tracks = provider.search("top hits vietnam")
                self.call_from_thread(self.set_home_recommendations, tracks, title)
            except Exception as exc:
                message = f"Home recommendations failed: {exc}"
                debug_log.warning("Home recommendations failed", provider=self.provider_name, error=str(exc))
                self.call_from_thread(lambda message=message: self.notify(message, severity="error"))

        threading.Thread(target=worker, daemon=True).start()

    def set_home_recommendations(self, tracks: Iterable[Track], title: str = "Recommended for you") -> None:
        self.home_recommendation_tracks = list(tracks)
        if self.current_view == "home":
            self.show_home(title)

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

    def load_artists_async(self, query: str) -> None:
        provider = self.providers["ytmusic"]

        def worker() -> None:
            try:
                artists = provider.search_artists(query)
                self.call_from_thread(self.set_artists, artists, f"Artists/channels: {query}")
            except Exception as exc:
                message = f"Artist search failed: {exc}"
                self.call_from_thread(lambda message=message: self.notify(message, severity="error"))

        threading.Thread(target=worker, daemon=True).start()

    def load_artist_tracks_async(self, artist: ArtistChannel, tab: str) -> None:
        provider = self.providers["ytmusic"]
        title = f"{artist.name}: {'Newest music' if tab == 'newest' else 'Popular / trending'}"
        self.set_loading(f"Loading {title}...")

        def worker() -> None:
            try:
                if tab == "newest":
                    tracks = provider.artist_newest_tracks(artist.id)
                else:
                    tracks = provider.artist_popular_tracks(artist.id)
                self.call_from_thread(self.set_tracks, tracks, title)
            except Exception as exc:
                message = f"Artist tracks failed: {exc}"
                self.call_from_thread(lambda message=message: self.notify(message, severity="error"))

        threading.Thread(target=worker, daemon=True).start()

    def update_search_suggestions(self, value: str) -> None:
        query = value.strip()
        self.suggestion_request_id += 1
        request_id = self.suggestion_request_id
        if not self.can_suggest_for(query):
            self.search_suggestions = []
            self.clear_search_suggestion_table()
            return

        local_suggestions = self.local_search_suggestions(query)
        self.set_search_suggestions(query, local_suggestions)
        provider = self.current_provider
        if not hasattr(provider, "search_suggestions"):
            if not local_suggestions:
                self.clear_search_suggestion_table()
            return
        if not local_suggestions:
            self.set_search_suggestion_loading(query)

        def worker() -> None:
            try:
                remote = provider.search_suggestions(query)
                self.call_from_thread(self.merge_remote_search_suggestions, request_id, query, remote)
            except Exception as exc:
                debug_log.warning("Search suggestions worker failed", provider=self.provider_name, error=str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def set_search_suggestion_loading(self, query: str) -> None:
        if not self.query_one("#search_input", Input).has_focus:
            return
        self.current_view = "suggestions"
        self.search_suggestions = []
        self.query_one("#feed_header", Static).update(f"Suggestions: {query}")
        table = self.query_one("#track_table", DataTable)
        table.clear(columns=True)
        table.add_columns("#", "Suggestion", "Source")
        table.add_row("...", "Looking up suggestions", self.provider_name, key="suggestion:loading")

    def clear_search_suggestion_table(self) -> None:
        if self.current_view != "suggestions":
            return
        self.current_view = "tracks"
        self.prepare_track_table()
        self.query_one("#feed_header", Static).update(self.feed_title)

    def can_suggest_for(self, query: str) -> bool:
        if len(query) < 2 or len(query) > 120:
            return False
        lowered = query.casefold()
        blocked_fragments = (
            "cookie:",
            "sapisid=",
            "__secure-3papisid=",
            "oauth_token",
            "access_token",
            "refresh_token",
            "authorization:",
            "http://127.0.0.1",
            "https://127.0.0.1",
        )
        return not any(fragment in lowered for fragment in blocked_fragments)

    def local_search_suggestions(self, query: str) -> list[tuple[str, str]]:
        needle = query.casefold()
        suggestions: list[tuple[str, str]] = []
        seen = set()

        def add(value: str, source: str) -> None:
            text = str(value or "").strip()
            key = text.casefold()
            if not text or needle not in key or key in seen:
                return
            suggestions.append((text, source))
            seen.add(key)

        for track in self.visible_tracks + self.library.history + self.library.active_playlist + self.library.queue:
            add(track.title, "Track")
            add(track.artist, "Artist")
            add(f"{track.artist} {track.title}", "Track")

        for cache_key in self.search_cache:
            provider, _, cached_query = str(cache_key).partition(":")
            if provider == self.provider_name:
                add(cached_query, "Recent search")

        return suggestions[:8]

    def set_search_suggestions(self, query: str, suggestions: list[tuple[str, str]]) -> None:
        if not self.query_one("#search_input", Input).has_focus:
            return
        if not suggestions:
            self.clear_search_suggestion_table()
            return

        self.current_view = "suggestions"
        self.search_suggestions = suggestions[:8]
        self.query_one("#feed_header", Static).update(f"Suggestions: {query}")
        self.query_one("#hero", Static).update(
            "[b]Search suggestions[/b]\n"
            "Keep typing, press Enter to search exactly, or Tab to the list and Enter to use a suggestion."
        )
        self.query_one("#tips", Static).update(
            "[b]Typing[/b]\n"
            "Ctrl+A selects all text in the Search box. Suggestions never run on cookie/token-looking input."
        )
        table = self.query_one("#track_table", DataTable)
        table.clear(columns=True)
        table.add_columns("#", "Suggestion", "Source")
        for idx, (suggestion, source) in enumerate(self.search_suggestions, start=1):
            table.add_row(str(idx), suggestion, source, key=f"suggestion:{idx - 1}")

    def merge_remote_search_suggestions(self, request_id: int, query: str, remote: list[str]) -> None:
        if request_id != self.suggestion_request_id:
            return
        current_query = self.query_one("#search_input", Input).value.strip()
        if current_query != query or not self.can_suggest_for(query):
            return

        merged = list(self.search_suggestions)
        seen = {suggestion.casefold() for suggestion, _source in merged}
        for item in remote:
            suggestion = str(item or "").strip()
            key = suggestion.casefold()
            if suggestion and key not in seen:
                merged.append((suggestion, "YT Music"))
                seen.add(key)
            if len(merged) >= 8:
                break
        self.set_search_suggestions(query, merged)

    def apply_search_suggestion(self, row_key) -> None:
        key = "" if row_key is None else str(row_key)
        if not key.startswith("suggestion:"):
            return
        try:
            index = int(key.split(":", 1)[1])
        except ValueError:
            return
        if not 0 <= index < len(self.search_suggestions):
            return

        suggestion = self.search_suggestions[index][0]
        search = self.query_one("#search_input", Input)
        self.suppress_suggestions = True
        try:
            search.value = suggestion
        finally:
            self.suppress_suggestions = False
        search.focus()
        search.cursor_position = len(suggestion)
        self.run_search()

    def play_track_async(self, track: Track) -> None:
        self.selected_track = track
        self.notify(f"Opening stream: {track.title}")

        def worker() -> None:
            provider_name, provider = self.provider_for_track(track)
            try:
                local_path = self.downloads.local_path_for(track)
                url = local_path or provider.get_stream_url(track.id)
                headers = {} if local_path else getattr(provider, "last_stream_headers", {})
                ok = self.player.play(url, 0, parse_duration(track.duration), headers)
                self.call_from_thread(self.on_play_started, ok, track, provider_name)
            except Exception as exc:
                message = f"Could not play track: {exc}"
                self.call_from_thread(lambda message=message: self.notify(message, severity="error"))

        threading.Thread(target=worker, daemon=True).start()

    def on_play_started(self, ok: bool, track: Track, provider_name: str) -> None:
        if not ok:
            self.autoplay_in_progress = False
            self.notify("Player could not start.", severity="error")
            return
        self.current_track = track
        self.provider_name = provider_name
        self.current_provider = self.providers[provider_name]
        self.playback_recovering = False
        self.playback_retries = 0
        self.autoplay_in_progress = False
        self.home_lyrics_last_index = -1
        self.library.add_to_history(track)
        self.downloads.record_play(track)
        self.downloads.maybe_auto_download(track)
        self.downloads.cleanup()
        self.load_next_suggestions_async(track)
        self.load_sponsor_segments_async(track)
        if self.home_lyrics_enabled:
            self.load_lyrics_async(track)
        if self.current_view == "home":
            self.show_home()
        self.update_presence_for_current(playing=True)
        self.refresh_player()
        self.update_static_panels()
        self.notify(f"Now playing: {track.title}")

    def next_track(self) -> None:
        next_item = self.library.pop_next_queue()
        if next_item:
            self.play_track_async(next_item)
            return

        next_item = self.pop_next_suggestion()
        if next_item:
            self.play_track_async(next_item)
            return

        playlist = self.library.active_playlist
        if not playlist:
            self.notify("Queue, suggestions, and playlist are empty.", severity="warning")
            return
        if not self.current_track:
            self.play_track_async(playlist[0])
            return
        current_index = next((idx for idx, item in enumerate(playlist) if item.id == self.current_track.id), -1)
        self.play_track_async(playlist[(current_index + 1) % len(playlist)])

    def play_next_after_finish(self) -> bool:
        if not self.downloads.settings.get("autoplay_suggestions_enabled"):
            return False
        if self.autoplay_in_progress:
            return True
        next_item = self.library.pop_next_queue()
        current_key = self.downloads.track_key(self.current_track) if self.current_track else ""
        if not next_item and current_key == self.next_suggestions_track_key and not self.next_suggestions_loaded:
            debug_log.debug("Autoplay waiting for next suggestions", track_key=current_key)
            return False
        next_item = next_item or self.pop_next_suggestion() or self.next_playlist_track()
        if not next_item:
            debug_log.debug("Autoplay finished with no next track")
            return False

        self.autoplay_in_progress = True
        debug_log.info(
            "Autoplaying next track",
            track_id=next_item.id,
            source=next_item.source,
            title=next_item.title,
        )
        self.notify(f"Autoplay next: {next_item.title}")
        self.play_track_async(next_item)
        return True

    def next_playlist_track(self) -> Track | None:
        playlist = self.library.active_playlist
        if not playlist:
            return None
        if not self.current_track:
            return playlist[0]
        current_index = next((idx for idx, item in enumerate(playlist) if item.id == self.current_track.id), -1)
        return playlist[(current_index + 1) % len(playlist)]

    def pop_next_suggestion(self) -> Track | None:
        current_key = self.downloads.track_key(self.current_track) if self.current_track else ""
        index = 0
        while index < len(self.suggested_next_tracks):
            item = self.suggested_next_tracks[index]
            if self.downloads.track_key(item) == current_key:
                self.suggested_next_tracks.pop(index)
                continue
            return self.suggested_next_tracks.pop(index)
        return None

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
            self.update_presence_for_current(playing=self.player.is_playing())
            self.refresh_player()
            self.notify(f"Jumped to {format_duration(self.player.elapsed_seconds())}.")
        else:
            self.notify("Could not seek this stream.", severity="error")

    def show_seek_input(self, default_value: str = "") -> None:
        if not self.current_track:
            self.notify("Play a track before seeking.", severity="warning")
            return
        row = self.query_one("#seek_row", Horizontal)
        row.remove_class("hidden")
        seek_input = self.query_one("#seek_input", Input)
        if default_value:
            seek_input.value = default_value
        seek_input.focus()
        seek_input.select_all()

    def hide_seek_input(self) -> None:
        self.query_one("#seek_row", Horizontal).add_class("hidden")
        self.query_one("#search_input", Input).focus()

    def seek_from_prompt(self) -> None:
        if not self.current_track:
            self.notify("Play a track before seeking.", severity="warning")
            return

        raw_value = self.query_one("#seek_input", Input).value.strip()
        self.seek_from_value(raw_value)

    def seek_from_value(self, raw_value: str) -> None:
        target = self.parse_seek_target(raw_value)
        if raw_value and target is not None:
            if self.player.seek_to(target):
                self.update_presence_for_current(playing=self.player.is_playing())
                self.hide_seek_input()
                self.refresh_player()
                self.notify(f"Jumped to {format_duration(self.player.elapsed_seconds())}.")
            else:
                self.notify("Could not seek this stream.", severity="error")
            return

        self.notify("Type a timestamp like 83, 1:23, or 01:02:03.", severity="warning")

    def parse_seek_target(self, value: str) -> int | None:
        text = str(value or "").strip()
        if not text:
            return None
        if text.isdigit():
            return int(text)
        if ":" in text:
            parsed = parse_duration(text)
            return parsed if parsed > 0 or text.replace(":", "").strip("0") == "" else None
        return None

    def load_sponsor_segments_async(self, track: Track) -> None:
        self.sponsor_segments = []
        self.sponsor_track_key = self.downloads.track_key(track)
        self.sponsor_skip_until = 0.0
        if not self.downloads.settings.get("sponsorblock_enabled"):
            return
        if "soundcloud" in track.source.lower() or track.id.startswith("http"):
            debug_log.debug("SponsorBlock skipped for non-YouTube track", source=track.source, track_id=track.id)
            return

        track_key = self.sponsor_track_key
        video_id = track.id

        def worker() -> None:
            segments = fetch_sponsor_segments(video_id)
            self.call_from_thread(self.set_sponsor_segments, track_key, segments)

        threading.Thread(target=worker, daemon=True).start()

    def set_sponsor_segments(self, track_key: str, segments: list[SponsorSegment]) -> None:
        if track_key != self.sponsor_track_key:
            return
        self.sponsor_segments = segments
        if segments:
            self.notify(f"SponsorBlock ready: {len(segments)} segment(s).")

    def maybe_skip_sponsor(self, elapsed: int) -> None:
        if not self.downloads.settings.get("sponsorblock_enabled"):
            return
        if not self.current_track or not self.player.is_playing() or not self.sponsor_segments:
            return
        if elapsed < self.sponsor_skip_until:
            return

        for segment in self.sponsor_segments:
            if segment.start <= elapsed < segment.end:
                target = int(segment.end) + 1
                if self.player.seek_to(target):
                    self.sponsor_skip_until = segment.end + 1.5
                    self.update_presence_for_current(playing=True)
                    self.notify(f"SponsorBlock skipped to {format_duration(target)}.")
                return

    def recover_playback_if_needed(self, elapsed: int) -> None:
        if not self.current_track or not self.player.ended_early():
            return
        if self.playback_recovering or self.playback_retries >= 3:
            return

        track = self.current_track
        provider_name, provider = self.provider_for_track(track)
        resume_at = max(0, elapsed)
        self.playback_recovering = True
        self.playback_retries += 1
        debug_log.warning(
            "Recovering early-ended playback",
            track_id=track.id,
            resume_at=str(resume_at),
            retry=str(self.playback_retries),
        )
        self.notify(f"Stream stopped early, reconnecting at {format_duration(resume_at)}...")

        def worker() -> None:
            try:
                local_path = self.downloads.local_path_for(track)
                url = local_path or provider.get_stream_url(track.id)
                headers = {} if local_path else getattr(provider, "last_stream_headers", {})
                ok = self.player.play(url, resume_at, parse_duration(track.duration), headers)
                self.call_from_thread(self.on_playback_recovered, ok, provider_name)
            except Exception as exc:
                message = f"Reconnect failed: {exc}"
                debug_log.exception("Playback recovery failed", error=str(exc))
                self.call_from_thread(self.on_playback_recovery_failed, message)

        threading.Thread(target=worker, daemon=True).start()

    def on_playback_recovered(self, ok: bool, provider_name: str) -> None:
        self.playback_recovering = False
        if ok:
            self.provider_name = provider_name
            self.current_provider = self.providers[provider_name]
            self.update_presence_for_current(playing=True)
            self.refresh_player()
            self.notify("Playback reconnected.")
        else:
            self.notify("Could not reconnect this stream.", severity="error")

    def on_playback_recovery_failed(self, message: str) -> None:
        self.playback_recovering = False
        self.notify(message, severity="error", timeout=8)

    def toggle_playback(self) -> None:
        if self.player.is_playing():
            elapsed = self.player.elapsed_seconds()
            self.player.stop()
            self.player.offset_seconds = elapsed
            self.update_presence_for_current(playing=False)
            self.refresh_player()
            self.notify(f"Stopped at {format_duration(elapsed)}. Press P to resume.")
            return

        if self.current_track and self.player.stream_url:
            if self.player.seek_to(self.player.offset_seconds):
                self.update_presence_for_current(playing=True)
                self.refresh_player()
                self.notify("Playback resumed.")
            else:
                self.notify("Could not resume this stream.", severity="error")
            return

        self.action_play_selected()

    def update_presence_for_current(self, playing: bool) -> None:
        if not self.current_track:
            self.presence.clear()
            return
        elapsed = self.player.elapsed_seconds()
        duration = parse_duration(self.current_track.duration)
        self.presence.set_track(
            self.current_track,
            self.provider_name,
            elapsed,
            duration,
            self.share_url_for(self.current_track),
            playing,
        )

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
        self.recover_playback_if_needed(elapsed)
        if self.player.finished() and not self.playback_recovering:
            if self.play_next_after_finish():
                return
        if self.player.is_playing():
            self.maybe_skip_sponsor(elapsed)
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
        if self.current_view == "home" and self.home_lyrics_enabled and self.lyric_lines:
            lyric_index = self.current_home_lyric_index()
            if lyric_index != self.home_lyrics_last_index:
                self.home_lyrics_last_index = lyric_index
                self.show_home(self.feed_title)

    def update_static_panels(self) -> None:
        connected = ", ".join(self.accounts.connected_platforms().keys()) or "No accounts"
        download_state = "Auto-download on" if self.downloads.settings.get("auto_download_played") else "Auto-download off"
        sponsor_state = "SponsorBlock on" if self.downloads.settings.get("sponsorblock_enabled") else "SponsorBlock off"
        autoplay_state = "Autoplay next on" if self.downloads.settings.get("autoplay_suggestions_enabled") else "Autoplay next off"
        lyrics_state = "Lyrics on" if self.home_lyrics_enabled else "Lyrics off"
        queue_count = len(self.library.queue)
        suggestion_count = len(self.suggested_next_tracks)
        hero = (
            "[b]Home[/b]\n"
            "Queue, upcoming suggestions, lyrics, and recommendations live together here.\n"
            f"[dim]Provider: {self.provider_name} | Queue: {queue_count} | Suggestions: {suggestion_count} | {lyrics_state} | Playlist: {self.library.active_playlist_name} | {connected} | {download_state} | {sponsor_state} | {autoplay_state}[/dim]"
        )
        tips = (
            "[b]Quick help for beginners[/b]\n"
            "Tab moves between boxes. Arrow keys move rows/buttons. Enter selects. "
            "Use the Lyrics button to hide/show lyrics in Home."
        )
        self.query_one("#hero", Static).update(hero)
        self.query_one("#tips", Static).update(tips)

    def set_loading(self, message: str) -> None:
        self.current_view = "tracks"
        self.query_one("#feed_header", Static).update(message)
        table = self.prepare_track_table()
        table.add_row("...", message, "Please wait", self.provider_name, "", key="loading")

    def set_tracks(self, tracks: Iterable[Track], title: str) -> None:
        self.current_view = "tracks"
        self.visible_tracks = list(tracks)
        self.selected_track = self.visible_tracks[0] if self.visible_tracks else None
        self.query_one("#feed_header", Static).update(title)
        table = self.prepare_track_table()
        if not self.visible_tracks:
            table.add_row("-", "No tracks found", "Try another search", self.provider_name, "", key="empty")
            return
        for idx, track in enumerate(self.visible_tracks, start=1):
            table.add_row(str(idx), track.title, track.artist, track.source, track.duration, key=str(idx - 1))
        table.focus()

    def prepare_track_table(self) -> DataTable:
        table = self.query_one("#track_table", DataTable)
        table.clear(columns=True)
        table.add_columns("#", "Title", "Artist", "Source", "Duration")
        return table

    def show_home(self, title: str = "Home") -> None:
        self.current_view = "home"
        self.feed_title = title
        self.update_static_panels()
        self.query_one("#feed_header", Static).update(title)
        table = self.query_one("#track_table", DataTable)
        table.clear(columns=True)
        table.add_columns("Section", "#", "Title", "Artist", "Source", "Duration")

        self.visible_tracks = []

        def add_track(section: str, track: Track) -> None:
            self.visible_tracks.append(track)
            table.add_row(
                section,
                str(len(self.visible_tracks)),
                track.title,
                track.artist,
                track.source,
                track.duration,
                key=str(len(self.visible_tracks) - 1),
            )

        queue_tracks = self.library.queue
        if queue_tracks:
            table.add_row("Queue", "-", f"{len(queue_tracks)} track(s) waiting", "Press N for queue order", "-", "", key="home:queue")
            for track in queue_tracks[:8]:
                add_track("Queue", track)

        if self.current_track:
            if self.suggested_next_tracks:
                table.add_row("Suggested", "-", f"Based on {self.current_track.title}", self.current_track.artist, self.current_track.source, "", key="home:suggested")
                for track in self.suggested_next_tracks[:10]:
                    add_track("Suggested", track)
            elif not self.next_suggestions_loaded:
                table.add_row("Suggested", "...", f"Loading suggestions for {self.current_track.title}", self.current_track.artist, self.current_track.source, "", key="home:suggested_loading")

            if not self.home_lyrics_enabled:
                table.add_row("Lyrics", "-", "Hidden", "Press Lyrics Off to show again", self.current_track.source, "", key="home:lyrics_hidden")
            else:
                if self.lyric_track_key != self.downloads.track_key(self.current_track):
                    self.load_lyrics_async(self.current_track)
                lyric_source = self.lyric_lines[0].source if self.lyric_lines else "official lyrics/subtitles only"
                if self.lyric_lines:
                    table.add_row("Lyrics", "-", lyric_source, "Enter timed lines to seek", self.current_track.source, "", key="home:lyrics")
                    for index, line in self.home_lyric_window():
                        timestamp = format_duration(line.start_seconds) if line.start_seconds is not None else "-"
                        action = "Enter to seek" if line.start_seconds is not None else "Text only"
                        table.add_row("Lyrics", timestamp, line.text, action, lyric_source, "", key=f"lyrics:{index}")
                elif not self.lyrics_loaded:
                    table.add_row("Lyrics", "...", f"Loading lyrics for {self.current_track.title}", "Official lyrics/subtitles only", self.current_track.source, "", key="home:lyrics_loading")
                elif self.lyrics_error:
                    table.add_row("Lyrics", "-", self.lyrics_error, "No auto-generated YouTube captions", self.current_track.source, "", key="home:lyrics_error")
                else:
                    table.add_row("Lyrics", "-", "No official lyrics or manually provided subtitles found", "Auto-generated YouTube captions are skipped", self.current_track.source, "", key="home:lyrics_empty")

        feed_tracks = self.home_recommendation_tracks or self.local_home_tracks()
        if feed_tracks:
            table.add_row("Home", "-", "Recommended for you", "Search/listening history", self.provider_name, "", key="home:feed")
            existing = {self.downloads.track_key(track) for track in self.visible_tracks}
            for track in feed_tracks:
                if self.downloads.track_key(track) in existing:
                    continue
                add_track("Home", track)
                existing.add(self.downloads.track_key(track))
                if len(self.visible_tracks) >= 24:
                    break

        if not self.visible_tracks:
            table.add_row("-", "-", "No tracks yet", "Search or play a track to build Home", self.provider_name, "", key="empty")
            self.selected_track = None
            return

        self.selected_track = self.visible_tracks[0]
        table.focus()

    def home_lyric_window(self, limit: int = 12) -> list[tuple[int, LyricLine]]:
        if not self.lyric_lines:
            return []
        timed = [
            (index, line)
            for index, line in enumerate(self.lyric_lines)
            if line.start_seconds is not None
        ]
        if not timed:
            return list(enumerate(self.lyric_lines[:limit]))

        elapsed = self.player.elapsed_seconds()
        current_position = 0
        for position, (_index, line) in enumerate(timed):
            if line.start_seconds is not None and line.start_seconds <= elapsed:
                current_position = position
            else:
                break
        start = max(0, current_position - 3)
        return timed[start:start + limit]

    def current_home_lyric_index(self) -> int:
        elapsed = self.player.elapsed_seconds()
        current_index = -1
        for index, line in enumerate(self.lyric_lines):
            if line.start_seconds is None:
                continue
            if line.start_seconds <= elapsed:
                current_index = index
            else:
                break
        return current_index

    def load_next_suggestions_async(self, track: Track) -> None:
        provider_name, provider = self.provider_for_track(track)
        if not hasattr(provider, "recommendations_for"):
            self.suggested_next_tracks = []
            return

        self.recommendation_request_id += 1
        request_id = self.recommendation_request_id
        track_key = self.downloads.track_key(track)
        self.next_suggestions_track_key = track_key
        self.suggested_next_tracks = []
        self.next_suggestions_loaded = False
        debug_log.debug("Loading next suggestions", provider=provider_name, track_id=track.id)

        def worker() -> None:
            try:
                tracks = provider.recommendations_for(track, 20)
                self.call_from_thread(self.set_next_suggestions, request_id, track_key, tracks)
            except Exception as exc:
                debug_log.warning(
                    "Next suggestions failed",
                    provider=provider_name,
                    track_id=track.id,
                    error=str(exc),
                )
                self.call_from_thread(self.set_next_suggestions, request_id, track_key, [])

        threading.Thread(target=worker, daemon=True).start()

    def set_next_suggestions(self, request_id: int, track_key: str, tracks: list[Track]) -> None:
        if request_id != self.recommendation_request_id or track_key != self.next_suggestions_track_key:
            return

        current_key = self.downloads.track_key(self.current_track) if self.current_track else ""
        self.suggested_next_tracks = [
            item for item in self.unique_tracks(tracks)
            if self.downloads.track_key(item) != current_key
        ][:20]
        self.next_suggestions_loaded = True
        debug_log.info(
            "Next suggestions ready",
            count=str(len(self.suggested_next_tracks)),
            track_key=track_key,
        )
        if self.current_view == "home":
            self.show_home()
        if self.player.finished() and not self.autoplay_in_progress:
            self.play_next_after_finish()

    def load_lyrics_async(self, track: Track) -> None:
        provider_name, provider = self.provider_for_track(track)
        self.lyric_track_key = self.downloads.track_key(track)
        self.lyrics_loaded = False
        self.lyrics_error = ""
        self.lyric_lines = []
        if not hasattr(provider, "get_lyrics"):
            self.set_lyrics(track, [], f"{track.source} does not expose lyrics.")
            return

        def worker() -> None:
            try:
                lyrics = provider.get_lyrics(track.id)
                self.call_from_thread(self.set_lyrics, track, lyrics, "")
            except Exception as exc:
                message = f"Lyrics failed: {exc}"
                debug_log.warning("Lyrics load failed", provider=provider_name, track_id=track.id, error=str(exc))
                self.call_from_thread(self.set_lyrics, track, [], message)

        threading.Thread(target=worker, daemon=True).start()

    def set_lyrics(self, track: Track, lines: list[LyricLine], error: str = "") -> None:
        active = self.current_track or self.selected_track
        if active and (active.id, active.source) != (track.id, track.source):
            return

        self.lyric_lines = lines
        self.lyrics_error = error
        self.lyrics_loaded = True
        self.home_lyrics_last_index = -1
        if self.current_view == "home":
            self.show_home()
            return

    def handle_lyric_row(self, row_key) -> None:
        key = "" if row_key is None else str(row_key)
        if not key.startswith("lyrics:"):
            return
        try:
            index = int(key.split(":", 1)[1])
        except ValueError:
            return
        if not 0 <= index < len(self.lyric_lines):
            return
        line = self.lyric_lines[index]
        if line.start_seconds is None:
            self.notify("This lyric line has no timestamp.", severity="warning")
            return
        self.seek_from_value(str(line.start_seconds))

    def set_artist_loading(self, message: str) -> None:
        self.current_view = "artist_results"
        self.query_one("#feed_header", Static).update(message)
        table = self.prepare_artist_table()
        table.add_row("...", message, "Please wait", "YTMusic", key="loading")

    def set_artists(self, artists: Iterable[ArtistChannel], title: str) -> None:
        self.current_view = "artist_results"
        self.visible_artists = list(artists)
        self.selected_artist = self.visible_artists[0] if self.visible_artists else None
        self.query_one("#feed_header", Static).update(title)
        self.query_one("#hero", Static).update(
            "[b]Artist / Channel Search[/b]\n"
            "Choose an artist/channel, then pick Newest music or Popular / trending."
        )
        self.query_one("#tips", Static).update(
            "[b]Artist tabs[/b]\n"
            "Newest pulls recent singles/albums. Popular / trending uses the artist's top songs on YouTube Music."
        )
        table = self.prepare_artist_table()
        if not self.visible_artists:
            table.add_row("-", "No artists found", "Try another name", "YTMusic", key="empty")
            return
        for idx, artist in enumerate(self.visible_artists, start=1):
            table.add_row(str(idx), artist.name, artist.subtitle or "-", artist.source, key=f"artist:{idx - 1}")
        table.focus()

    def prepare_artist_table(self) -> DataTable:
        table = self.query_one("#track_table", DataTable)
        table.clear(columns=True)
        table.add_columns("#", "Artist / Channel", "Info", "Source")
        return table

    def open_artist_from_key(self, row_key) -> None:
        if row_key is None:
            return
        key = str(row_key)
        if not key.startswith("artist:"):
            return
        try:
            index = int(key.split(":", 1)[1])
        except ValueError:
            return
        if 0 <= index < len(self.visible_artists):
            self.selected_artist = self.visible_artists[index]
            self.show_artist_tabs(self.selected_artist)

    def show_artist_tabs(self, artist: ArtistChannel) -> None:
        self.current_view = "artist_tabs"
        self.selected_artist = artist
        self.query_one("#feed_header", Static).update(f"Artist/channel: {artist.name}")
        self.query_one("#hero", Static).update(
            f"[b]{artist.name}[/b]\n"
            f"{artist.subtitle or 'Choose which music list to open.'}"
        )
        self.query_one("#tips", Static).update(
            "[b]Choose a tab[/b]\n"
            "Newest music shows recent release tracks. Popular / trending shows top songs by current YouTube Music ranking."
        )
        table = self.query_one("#track_table", DataTable)
        table.clear(columns=True)
        table.add_columns("Tab", "What it shows", "Action")
        table.add_row("Newest music", "Recent singles/albums from this artist/channel", "Open", key="artist_tab:newest")
        table.add_row("Popular / trending", "Top songs with current YouTube Music ranking", "Open", key="artist_tab:popular")
        table.add_row("Back to artist search", "Return to artist/channel results", "Back", key="artist_tab:back")
        table.focus()

    def handle_artist_tab(self, row_key) -> None:
        key = "" if row_key is None else str(row_key)
        if not key.startswith("artist_tab:"):
            return
        action = key.split(":", 1)[1]
        if action == "back":
            self.set_artists(self.visible_artists, "Artists/channels")
            return
        if not self.selected_artist:
            self.notify("Choose an artist/channel first.", severity="warning")
            return
        self.load_artist_tracks_async(self.selected_artist, action)

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
            "For YouTube Music, paste a music.youtube.com Cookie value into Search and click Connect provider."
        )
        self.query_one("#tips", Static).update(
            "[b]Login[/b]\n"
            "YouTube Music uses browser cookie auth like Metrolist. "
            "SoundCloud and Spotify still use OAuth callback/code."
        )
        table = self.query_one("#track_table", DataTable)
        table.clear(columns=True)
        table.add_columns("Platform", "Status", "Label", "Last sync", "Token", "Action")
        for platform in sorted(SUPPORTED_PLATFORMS):
            account = accounts.get(platform, {})
            is_connected = isinstance(account, dict) and bool(account)
            is_pending = isinstance(pending.get(platform), dict)
            status = "Connected" if is_connected else "Waiting for callback" if is_pending else "Not connected"
            token_state = (
                "Browser cookie saved"
                if account.get("auth_type") == "browser_cookie"
                else "OAuth token saved"
                if account.get("access_token") or account.get("token")
                else "No token"
            )
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
        table.focus()

    def show_download_manager(self) -> None:
        self.current_view = "downloads"
        settings = self.downloads.settings
        stats = self.downloads.stats()
        size_mb = stats["bytes"] / (1024 * 1024)
        self.query_one("#feed_header", Static).update("Downloads")
        self.query_one("#hero", Static).update(
            "[b]Downloads[/b]\n"
            f"Saved tracks: {stats['count']} | Disk: {size_mb:.1f} MB | Folder: {self.downloads.download_dir}"
        )
        self.query_one("#tips", Static).update(
            "[b]Navigation[/b]\n"
            "Tab switches boxes. Up/Down chooses an action. Enter applies the selected download setting."
        )

        table = self.query_one("#track_table", DataTable)
        table.clear(columns=True)
        table.add_columns("Setting", "Current", "Action")
        auto_state = "On" if settings.get("auto_download_played") else "Off"
        autoplay_state = "On" if settings.get("autoplay_suggestions_enabled") else "Off"
        sponsor_state = "On" if settings.get("sponsorblock_enabled") else "Off"
        table.add_row("Auto-download played tracks", auto_state, "Toggle", key="download:toggle_auto")
        table.add_row("Autoplay recommendations", autoplay_state, "Toggle", key="download:toggle_autoplay")
        table.add_row("SponsorBlock", sponsor_state, "Toggle", key="download:toggle_sponsorblock")
        table.add_row("Cleanup age", f"{settings['cleanup_days']} day(s)", "-1 day", key="download:days_down")
        table.add_row("Cleanup age", f"{settings['cleanup_days']} day(s)", "+1 day", key="download:days_up")
        table.add_row("Keep if played at least", str(settings["cleanup_min_plays"]), "-1 play", key="download:plays_down")
        table.add_row("Keep if played at least", str(settings["cleanup_min_plays"]), "+1 play", key="download:plays_up")
        table.add_row("Cleanup now", f"Delete older than {settings['cleanup_days']} day(s) with < {settings['cleanup_min_plays']} play(s)", "Run", key="download:cleanup")
        table.add_row("Back home", "Return to recommendations", "Open", key="download:home")
        table.focus()

    def handle_download_action(self, row_key) -> None:
        key = "" if row_key is None else str(row_key)
        if not key.startswith("download:"):
            return
        action = key.split(":", 1)[1]
        settings = self.downloads.settings
        if action == "toggle_auto":
            self.downloads.set_auto_download(not bool(settings.get("auto_download_played")))
            self.notify("Auto-download toggled.")
        elif action == "toggle_autoplay":
            enabled = not bool(settings.get("autoplay_suggestions_enabled"))
            self.downloads.set_autoplay_suggestions(enabled)
            self.notify(f"Autoplay recommendations {'enabled' if enabled else 'disabled'}.")
        elif action == "toggle_sponsorblock":
            enabled = not bool(settings.get("sponsorblock_enabled"))
            self.downloads.set_sponsorblock(enabled)
            self.notify(f"SponsorBlock {'enabled' if enabled else 'disabled'}.")
            if enabled and self.current_track:
                self.load_sponsor_segments_async(self.current_track)
            elif not enabled:
                self.sponsor_segments = []
        elif action == "days_down":
            self.downloads.set_cleanup_days(int(settings["cleanup_days"]) - 1)
        elif action == "days_up":
            self.downloads.set_cleanup_days(int(settings["cleanup_days"]) + 1)
        elif action == "plays_down":
            self.downloads.set_cleanup_min_plays(int(settings["cleanup_min_plays"]) - 1)
        elif action == "plays_up":
            self.downloads.set_cleanup_min_plays(int(settings["cleanup_min_plays"]) + 1)
        elif action == "cleanup":
            result = self.downloads.cleanup()
            self.notify(f"Cleanup removed {result['removed']} file(s), kept {result['kept']}.")
        elif action == "home":
            self.action_home()
            return
        self.show_download_manager()

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
            "[b]Navigation[/b]\n"
            "Tab switches boxes. Up/Down chooses an action. Enter selects. "
            "Use Auto import for browser cookies/tokens, or Paste from Search for manual values."
        )

        table = self.query_one("#track_table", DataTable)
        table.clear(columns=True)
        table.add_columns("Action", "What it does", "When to use")
        if provider == "ytmusic":
            table.add_row("Auto import browser cookie", "Read YouTube Music cookie from Edge/Chrome/Brave/Firefox", "Recommended", key="action:auto_import")
            table.add_row("Paste cookie from Search", "Save Cookie header currently typed in Search", "If auto import fails", key="action:paste_auth")
            table.add_row("Open YouTube Music login", "Open login page and copy URL", "If browser is not logged in", key="action:open_login")
        elif provider == "soundcloud":
            table.add_row("Auto import browser token", "Read SoundCloud oauth_token from Edge/Chrome/Brave/Firefox", "Recommended", key="action:auto_import")
            table.add_row("Paste token from Search", "Save oauth_token currently typed in Search", "If auto import fails", key="action:paste_auth")
            table.add_row("Official OAuth login", "Open OAuth flow using configured client credentials", "If you have API credentials", key="action:connect")
        else:
            table.add_row("OAuth login", "Open browser OAuth flow and auto-capture callback", "First setup or token expired", key="action:connect")
        table.add_row("Sync now", "Save current queue/history/playlist snapshot to this account record", "After changing playlist/queue", key="action:sync")
        table.add_row("Disconnect", "Remove saved token/account for this provider", "When switching account", key="action:logout")
        table.add_row("Back to Account Manager", "Return to account list", "Review all linked accounts", key="action:back")
        table.focus()

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
        elif action == "auto_import":
            self.auto_import_provider_auth(provider)
        elif action == "paste_auth":
            self.paste_provider_auth(provider)
        elif action == "open_login":
            self.open_provider_login(provider)
        elif action == "sync":
            self.sync_library()
        elif action == "logout":
            self.logout_current_provider()
        elif action == "back":
            self.show_account_manager()

    def auto_import_provider_auth(self, provider: str) -> None:
        debug_log.info("TUI auto import requested", provider=provider)
        try:
            if provider == "ytmusic":
                account = self.accounts.login_ytmusic_browser_cookie()
                self.refresh_provider_auth("ytmusic")
                self.notify(f"Imported YouTube Music cookie from {account.get('browser', 'browser')}.")
            elif provider == "soundcloud":
                account = self.accounts.login_soundcloud_browser_token()
                self.refresh_provider_auth("soundcloud")
                self.notify(f"Imported SoundCloud token from {account.get('browser', 'browser')}.")
            else:
                self.connect_current_provider()
                return
            self.update_static_panels()
            if self.current_view == "accounts":
                self.show_account_manager()
            else:
                self.show_account_actions(provider)
        except Exception as exc:
            debug_log.exception("TUI auto import failed", provider=provider, error=str(exc))
            self.notify(f"Auto import failed: {exc}", severity="error", timeout=10)
            self.show_account_actions(provider)

    def paste_provider_auth(self, provider: str) -> None:
        value = self.query_one("#search_input", Input).value.strip()
        debug_log.info("TUI manual auth requested", provider=provider, input_length=str(len(value)))
        try:
            if provider == "ytmusic":
                cookie = extract_cookie_from_input(value)
                debug_log.debug("TUI ytmusic manual cookie parsed", cookie_present=str(bool(cookie)))
                if not cookie:
                    raise ValueError("Paste a music.youtube.com Cookie header into Search first.")
                self.accounts.login_ytmusic_cookie(cookie)
                self.refresh_provider_auth("ytmusic")
                self.clear_search_bar(notify=False)
                self.notify("YouTube Music cookie connected.")
            elif provider == "soundcloud":
                token = extract_soundcloud_token(value)
                if not token:
                    raise ValueError("Paste a SoundCloud oauth_token into Search first.")
                self.accounts.login_soundcloud_token(token)
                self.refresh_provider_auth("soundcloud")
                self.clear_search_bar(notify=False)
                self.notify("SoundCloud OAuth token connected.")
            else:
                self.connect_current_provider()
                return
            self.update_static_panels()
            self.show_account_actions(provider)
        except Exception as exc:
            debug_log.exception("TUI manual auth failed", provider=provider, error=str(exc))
            self.notify(f"Manual login failed: {exc}", severity="error", timeout=10)

    def open_provider_login(self, provider: str) -> None:
        if provider == "ytmusic":
            url = "https://accounts.google.com/ServiceLogin?continue=https%3A%2F%2Fmusic.youtube.com"
            self.copy_to_clipboard(url)
            try:
                webbrowser.open(url)
            except Exception:
                pass
            self.notify("YouTube Music login URL opened and copied. After login, choose Auto import browser cookie.", timeout=10)
        elif provider == "soundcloud":
            try:
                webbrowser.open("https://soundcloud.com/signin")
            except Exception:
                pass
            self.notify("SoundCloud login opened. After login, choose Auto import browser token.", timeout=10)

    def show_account_login_guide(self, provider: str, error: str = "") -> None:
        self.current_view = "account_actions"
        prefix = "GOOGLE" if provider == "ytmusic" else provider.upper()
        redirect = DEFAULT_REDIRECT_URI
        setup_url = "" if provider == "ytmusic" else self.open_oauth_setup(provider)
        self.query_one("#feed_header", Static).update(f"Login guide: {provider}")
        if provider == "ytmusic":
            reason = f"\n[red]{error}[/red]" if error else ""
            self.query_one("#hero", Static).update(
                "[b]ytmusic login[/b]\n"
                "Soundtify can import cookies from Edge, Chrome, Brave, or Firefox. "
                f"If auto-import fails, open music.youtube.com, copy the request Cookie header, paste it into Search, then choose Login / Connect.{reason}"
            )
            self.query_one("#tips", Static).update(
                "[b]Cookie auth[/b]\n"
                "The cookie must include SAPISID or __Secure-3PAPISID. "
                "Soundtify will build SAPISIDHASH headers automatically."
            )
        elif provider == "soundcloud":
            reason = f"\n[red]{error}[/red]" if error else ""
            self.query_one("#hero", Static).update(
                "[b]soundcloud login[/b]\n"
                "Soundtify can import oauth_token from Edge, Chrome, Brave, or Firefox. "
                f"If auto-import fails, paste an oauth_token or finish the official OAuth setup.{reason}"
            )
            self.query_one("#tips", Static).update(
                "[b]SoundCloud auth[/b]\n"
                "Browser oauth_token is passed to yt-dlp as SoundCloud OAuth. "
                "Official API credentials still work if you have client_id/client_secret."
            )
        else:
            reason = f"\n[red]{error}[/red]" if error else ""
            self.query_one("#hero", Static).update(
                f"[b]{provider} login[/b]\n"
                f"Opened local setup page: {setup_url}{reason}"
            )
            self.query_one("#tips", Static).update(
                "[b]SoundCloud note[/b]\n"
                "SoundCloud OAuth token exchange requires both client_id and client_secret. "
                "Fill the browser form, save it, then return here and choose Login / Connect."
            )
        table = self.query_one("#track_table", DataTable)
        table.clear(columns=True)
        table.add_columns("Setting", "Value")
        if provider == "ytmusic":
            table.add_row("Login URL", "https://accounts.google.com/ServiceLogin?continue=https%3A%2F%2Fmusic.youtube.com", key="guide:url")
            table.add_row("Required cookie", "SAPISID or __Secure-3PAPISID from music.youtube.com", key="guide:cookie")
            table.add_row("How to save", "Paste Cookie header into Search, then Login / Connect", key="guide:save")
            table.add_row("Auth style", "Metrolist-style cookie + SAPISIDHASH", key="guide:style")
        elif provider == "soundcloud":
            table.add_row("Auto import", "Reads oauth_token from Edge/Chrome/Brave/Firefox", key="guide:auto")
            table.add_row("Manual token", "Paste oauth_token into Search, then Login / Connect", key="guide:token")
            table.add_row("Official OAuth", "Use local setup page if you have SoundCloud API credentials", key="guide:oauth")
            table.add_row("Local setup URL", setup_url, key="guide:url")
        else:
            table.add_row("Local setup URL", setup_url, key="guide:url")
            table.add_row("Redirect URI", redirect, key="guide:redirect")
            table.add_row("Client ID env var", f"SOUNDTIFY_{prefix}_CLIENT_ID", key="guide:client_id")
            table.add_row("Client secret env var", f"SOUNDTIFY_{prefix}_CLIENT_SECRET", key="guide:client_secret")
            table.add_row("Config file", "auth_config.json in Soundtify app data, written by the browser form", key="guide:file")
        table.add_row("Back", "Press Enter to return to action menu", key="action:back")
        table.focus()

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
        debug_log.info("TUI connect requested", provider=self.provider_name, input_length=str(len(value)))
        if self.provider_name == "ytmusic":
            self.show_account_actions("ytmusic")
            self.notify("Choose Auto import browser cookie or Paste cookie from Search.", timeout=8)
            return

        if self.provider_name == "soundcloud":
            self.show_account_actions("soundcloud")
            self.notify("Choose Auto import browser token, Paste token from Search, or Official OAuth login.", timeout=8)
            return

        code, state = self.extract_auth_callback(value)
        pending = self.accounts.pending_oauth(self.provider_name)
        if code and pending:
            expected_state = pending.get("state")
            if state and expected_state and state != expected_state:
                self.notify("OAuth state mismatch. Click Connect again to start over.", severity="error")
                return
            try:
                self.accounts.finish_oauth(self.provider_name, code)
                self.refresh_provider_auth(self.provider_name)
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
            if self.provider_name in {"soundcloud", "spotify"}:
                self.show_account_login_guide(self.provider_name, str(exc))
                return
            self.notify(f"OAuth start failed: {exc}", severity="error", timeout=10)
        if self.current_view == "accounts":
            self.show_account_manager()

    def logout_current_provider(self) -> None:
        if self.accounts.logout(self.provider_name):
            self.refresh_provider_auth(self.provider_name)
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
                self.call_from_thread(self.refresh_provider_auth, platform)
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

    def refresh_provider_auth(self, platform: str) -> None:
        provider = self.providers.get(platform)
        if hasattr(provider, "refresh_auth"):
            provider.refresh_auth()

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
            Track("help5", "Keyboard", "P play/stop, J -15s, K +15s, N next, B back, S search, Ctrl+A select all, Q quit.", "Help", ""),
            Track("help6", "Lyrics", "Home shows lyrics automatically. Use Lyrics On/Off to hide or show them.", "Help", ""),
            Track("help7", "Seek", "Click Seek to open a timestamp box. Timed lyric lines can seek directly.", "Help", ""),
            Track("help8", "Home queue", "Home shows queue, upcoming suggestions, and recommendations in one compact list.", "Help", ""),
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
