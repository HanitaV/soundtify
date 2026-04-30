import sys
from src.ui.app import SoundtifyApp
from src.ui.tui import SoundtifyTUI

def configure_console_encoding():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

def main():
    configure_console_encoding()
    if "--classic" in sys.argv:
        app = SoundtifyApp()
        try:
            app.run()
        finally:
            app.shutdown_audio()
        return

    app = SoundtifyTUI()
    try:
        app.run()
    finally:
        app.shutdown_audio()

if __name__ == "__main__":
    main()
