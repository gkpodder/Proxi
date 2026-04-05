"""Browser agent configuration."""

from dataclasses import dataclass, field
from pathlib import Path


def _default_profile_dir() -> Path:
    return Path.home() / ".proxi" / "browser_profile"


@dataclass
class BrowserAgentConfig:
    """Configuration for the Proxi browser agent."""

    # Path to the persistent Chrome/Chromium profile directory.
    # Kept separate from the user's personal browser profile.
    profile_dir: Path = field(default_factory=_default_profile_dir)

    # Show the browser window (False = run headless).
    # Default is visible so the user can watch/intervene.
    headless: bool = False

    # Per-action Playwright timeout in milliseconds (navigation, element waits).
    # 60 s is generous enough for slow sites without hanging forever.
    timeout_ms: int = 60_000

    # Slow down each Playwright action by this many ms (useful for debugging).
    slow_mo_ms: int = 0

    def ensure_profile_dir(self) -> None:
        """Create the profile directory if it doesn't exist."""
        self.profile_dir.mkdir(parents=True, exist_ok=True)


# Module-level default config — tools and session share this instance.
DEFAULT_CONFIG = BrowserAgentConfig()
