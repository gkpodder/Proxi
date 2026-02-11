"""Auto-detection and configuration for MCP integrations."""

import os
import sys
import json
import shlex
from pathlib import Path
from typing import Any


class MCPAutoConfig:
    """Manages auto-detection and loading of MCP integrations."""

    # Keywords that trigger auto-loading of integrations
    INTEGRATION_KEYWORDS = {
        "gmail": [
            "email", "gmail", "inbox", "mail", "message",
            "send email", "read email", "unread", "compose",
            "sender", "recipient", "subject line"
        ],
        "calendar": [
            "calendar", "event", "meeting", "schedule",
            "appointment", "remind", "availability"
        ],
        "notion": [
            "notion", "page", "database", "note",
            "workspace", "document"
        ],
    }

    # Default config location
    DEFAULT_CONFIG_PATH = Path.home() / ".proxi" / "mcp_config.json"

    def __init__(self, config_path: Path | None = None):
        """
        Initialize auto-config manager.

        Args:
            config_path: Optional custom config path
        """
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        self.config = self._load_config()

    def _load_config(self) -> dict[str, Any]:
        """Load configuration from file."""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return self._get_default_config()

    def _get_default_config(self) -> dict[str, Any]:
        """Get default configuration."""
        return {
            "auto_load": {
                "enabled": True,
                "integrations": {
                    "gmail": {
                        "enabled": True,
                        "credentials_path": "gmail_credentials.json",
                        "token_path": "gmail_token.json",
                    },
                    "calendar": {
                        "enabled": False,
                    },
                    "notion": {
                        "enabled": False,
                    },
                },
            },
        }

    def save_config(self) -> None:
        """Save current configuration to file."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w") as f:
            json.dump(self.config, f, indent=2)

    def is_auto_load_enabled(self) -> bool:
        """Check if auto-loading is enabled."""
        return self.config.get("auto_load", {}).get("enabled", True)

    def detect_integrations(self, task: str) -> list[str]:
        """
        Detect which integrations should be loaded based on task text.

        Args:
            task: The task description

        Returns:
            List of integration names to load
        """
        if not self.is_auto_load_enabled():
            return []

        task_lower = task.lower()
        detected = []

        for integration, keywords in self.INTEGRATION_KEYWORDS.items():
            # Check if integration is enabled in config
            integration_config = (
                self.config.get("auto_load", {})
                .get("integrations", {})
                .get(integration, {})
            )
            
            if not integration_config.get("enabled", False):
                continue

            # Check if any keyword matches
            if any(keyword in task_lower for keyword in keywords):
                detected.append(integration)

        return detected

    def get_mcp_command(self, integrations: list[str]) -> str | None:
        """
        Get MCP server command for the detected integrations.

        Args:
            integrations: List of integration names

        Returns:
            MCP server command string or None if no integrations
        """
        if not integrations:
            return None

        # Build command for unified server
        args = []
        
        for integration in integrations:
            integration_config = (
                self.config.get("auto_load", {})
                .get("integrations", {})
                .get(integration, {})
            )
            
            if integration == "gmail":
                args.append("--enable-gmail")
            # Add other integrations here as they're implemented
            # elif integration == "calendar":
            #     args.append("--enable-calendar")

        if not args:
            return None

        # Build the command - use sys.executable to ensure same Python environment
        # Use space-separated format with proper quoting for Windows paths
        python_exe = sys.executable
        cmd_parts = [python_exe, "-m", "proxi.mcp.servers.unified_server"] + args
        # Return as space-separated string with proper quoting
        return " ".join(shlex.quote(part) for part in cmd_parts)

    def get_integration_config(self, integration: str) -> dict[str, Any]:
        """Get configuration for a specific integration."""
        return (
            self.config.get("auto_load", {})
            .get("integrations", {})
            .get(integration, {})
        )

    def set_integration_enabled(self, integration: str, enabled: bool) -> None:
        """Enable or disable an integration."""
        if "auto_load" not in self.config:
            self.config["auto_load"] = self._get_default_config()["auto_load"]
        
        if "integrations" not in self.config["auto_load"]:
            self.config["auto_load"]["integrations"] = {}
        
        if integration not in self.config["auto_load"]["integrations"]:
            self.config["auto_load"]["integrations"][integration] = {}
        
        self.config["auto_load"]["integrations"][integration]["enabled"] = enabled
        self.save_config()

    def check_prerequisites(self, integration: str) -> tuple[bool, str]:
        """
        Check if prerequisites are met for an integration.

        Args:
            integration: Integration name

        Returns:
            Tuple of (success, message)
        """
        if integration == "gmail":
            # Check if google libraries are installed
            try:
                import google.auth  # noqa: F401
                import google_auth_oauthlib  # noqa: F401
                import googleapiclient  # noqa: F401
            except ImportError:
                return (
                    False,
                    "Gmail integration requires additional packages. "
                    "Install with: uv pip install -e \".[gmail]\""
                )
            
            # Check for credentials - either env vars or file
            client_id = os.getenv("GMAIL_CLIENT_ID")
            client_secret = os.getenv("GMAIL_CLIENT_SECRET")
            
            config = self.get_integration_config("gmail")
            creds_path = config.get("credentials_path", "gmail_credentials.json")
            
            # Accept either environment variables OR credentials file
            has_env_creds = client_id and client_secret
            has_file_creds = os.path.exists(creds_path)
            
            if not has_env_creds and not has_file_creds:
                return (
                    False,
                    f"Gmail credentials not found. Either: \n"
                    f"1. Set environment variables: GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET\n"
                    f"2. Or provide credentials file at {creds_path}\n"
                    "See GMAIL_SETUP.md for setup instructions."
                )
            
            return (True, "Gmail prerequisites met")
        
        return (True, f"No prerequisites defined for {integration}")


# Global instance
_auto_config: MCPAutoConfig | None = None


def get_auto_config() -> MCPAutoConfig:
    """Get the global auto-config instance."""
    global _auto_config
    if _auto_config is None:
        _auto_config = MCPAutoConfig()
    return _auto_config
