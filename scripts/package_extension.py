from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path


DEFAULT_EXTENSION_DIR = Path("extensions/chromium-cookie-helper")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and package the Soundtify Chromium extension.")
    parser.add_argument("--extension-dir", default=str(DEFAULT_EXTENSION_DIR))
    parser.add_argument("--out-dir", default="artifacts")
    parser.add_argument("--name", default="soundtify-cookie-helper")
    args = parser.parse_args()

    extension_dir = Path(args.extension_dir)
    manifest = load_manifest(extension_dir / "manifest.json")
    version = manifest["version"]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"{args.name}-v{version}.zip"
    package_extension(extension_dir, zip_path, args.name)
    print(f"Packaged {manifest['name']} v{version}: {zip_path}")
    return 0


def load_manifest(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing manifest: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    required = ("manifest_version", "name", "version", "action")
    missing = [key for key in required if key not in manifest]
    if missing:
        raise ValueError(f"Manifest is missing required field(s): {', '.join(missing)}")
    if manifest["manifest_version"] != 3:
        raise ValueError("Only Manifest V3 is supported.")
    return manifest


def package_extension(extension_dir: Path, zip_path: Path, root_name: str) -> None:
    included = []
    for path in sorted(extension_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith("."):
            continue
        relative = path.relative_to(extension_dir).as_posix()
        included.append((path, f"{root_name}/{relative}"))

    if not included:
        raise RuntimeError(f"No extension files found in {extension_dir}")

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, archive_name in included:
            archive.write(path, archive_name)


if __name__ == "__main__":
    raise SystemExit(main())
