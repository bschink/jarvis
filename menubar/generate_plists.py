"""
generate_plists.py — substitute real paths into launchd plist templates and
install them into ~/Library/LaunchAgents/.

Handles two new plists:
  com.jarvis.menubar  — auto-start the menu bar app at login
  com.openwebui       — Open WebUI (started on demand via the menu bar)

Reads ~/.jarvis/menubar_config.json for dynamic values (ollama_keep_alive).
Existing plists (whisper, kokoro, etc.) are not touched — install.sh owns those.

Usage:
    uv run python menubar/generate_plists.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parent.parent.resolve()
LAUNCHD_DIR = REPO_ROOT / "launchd"
MENUBAR_DIR = REPO_ROOT / "menubar"
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"

VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
MENUBAR_SCRIPT = MENUBAR_DIR / "app.py"

CONFIG_PATH = Path.home() / ".jarvis" / "menubar_config.json"
DEFAULT_KEEP_ALIVE = "10m"


def _load_keep_alive() -> str:
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open() as f:
                return str(json.load(f).get("ollama_keep_alive", DEFAULT_KEEP_ALIVE))
        except json.JSONDecodeError, OSError:
            pass
    return DEFAULT_KEEP_ALIVE


def _get_or_create_webui_secret_key() -> str:
    """Return a stable WEBUI_SECRET_KEY, generating and persisting it on first run."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    config: dict = {}
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open() as f:
                config = json.load(f)
        except json.JSONDecodeError, OSError:
            pass
    if "webui_secret_key" not in config:
        config["webui_secret_key"] = secrets.token_hex(32)
        with CONFIG_PATH.open("w") as f:
            json.dump(config, f, indent=2)
    return str(config["webui_secret_key"])


def _substitutions() -> dict[str, str]:
    return {
        "YOURUSERNAME": Path.home().name,
        "JARVIS_VENV_PYTHON": str(VENV_PYTHON),
        "JARVIS_MENUBAR_SCRIPT": str(MENUBAR_SCRIPT),
        "JARVIS_MENUBAR_DIR": str(MENUBAR_DIR),
        "WEBUI_SECRET_KEY_VALUE": _get_or_create_webui_secret_key(),
    }


def generate(dry_run: bool = False) -> None:
    LAUNCH_AGENTS.mkdir(parents=True, exist_ok=True)
    subs = _substitutions()
    keep_alive = _load_keep_alive()
    targets = ["com.jarvis.menubar.plist", "com.openwebui.plist"]

    for filename in targets:
        template_path = LAUNCHD_DIR / filename
        if not template_path.exists():
            print(f"  [SKIP] Template not found: {template_path}", file=sys.stderr)
            continue

        text = template_path.read_text()
        for placeholder, value in subs.items():
            text = text.replace(placeholder, value)

        dest = LAUNCH_AGENTS / filename
        if dry_run:
            print(f"  [DRY RUN] Would write {dest}:")
            print(text)
        else:
            dest.write_text(text)
            print(f"  [OK] {dest}")

    # Patch OLLAMA_KEEP_ALIVE into the Homebrew Ollama plist if it's present
    # and the env var is not already set there.
    ollama_plist = LAUNCH_AGENTS / "homebrew.mxcl.ollama.plist"
    if ollama_plist.exists():
        _patch_ollama_keep_alive(ollama_plist, keep_alive, dry_run)


def _patch_ollama_keep_alive(plist_path: Path, value: str, dry_run: bool) -> None:
    """
    Add OLLAMA_KEEP_ALIVE to the Homebrew Ollama plist's EnvironmentVariables
    if it is not already present.  Uses string substitution rather than plistlib
    so we don't disturb the existing whitespace/comments.
    """
    text = plist_path.read_text()
    if "OLLAMA_KEEP_ALIVE" in text:
        print(f"  [SKIP] OLLAMA_KEEP_ALIVE already set in {plist_path.name}")
        return

    # Insert after <key>EnvironmentVariables</key>\n\t<dict>
    insert_after = "<key>EnvironmentVariables</key>"
    if insert_after not in text:
        print(
            f"  [WARN] Could not find EnvironmentVariables key in {plist_path.name}; "
            "set OLLAMA_KEEP_ALIVE manually.",
            file=sys.stderr,
        )
        return

    # Build the new entries to insert right inside the EnvironmentVariables dict.
    new_entries = f"\n\t\t<key>OLLAMA_KEEP_ALIVE</key>\n\t\t<string>{value}</string>"
    # Find the opening <dict> that follows <key>EnvironmentVariables</key>
    ev_pos = text.index(insert_after)
    dict_pos = text.index("<dict>", ev_pos) + len("<dict>")
    patched = text[:dict_pos] + new_entries + text[dict_pos:]

    if dry_run:
        print(f"  [DRY RUN] Would patch OLLAMA_KEEP_ALIVE={value} in {plist_path}")
    else:
        plist_path.write_text(patched)
        print(f"  [OK] Patched OLLAMA_KEEP_ALIVE={value} in {plist_path.name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate and install JARVIS launchd plists")
    parser.add_argument("--dry-run", action="store_true", help="Print output without writing files")
    args = parser.parse_args()

    print("Generating launchd plists...")
    generate(dry_run=args.dry_run)
    print("Done.")
