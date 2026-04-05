"""Playwright browser session manager for Proxi's individual browser tools.

A single persistent BrowserContext is shared across all individual browser_*
tool calls within a process.  The context uses a dedicated user-data-dir
(~/.proxi/browser_profile/) so Proxi never touches the user's personal browser
sessions.

Usage
-----
    from proxi.browser.session import get_page, close_session

    page = await get_page()          # lazily starts browser on first call
    await page.goto("https://...")
    await close_session()            # call on agent shutdown
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from proxi.browser.config import DEFAULT_CONFIG, BrowserAgentConfig
from proxi.observability.logging import get_logger

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page, Playwright

logger = get_logger(__name__)

_lock = asyncio.Lock()


class BrowserSession:
    """Manages a persistent Playwright BrowserContext with Proxi's own profile."""

    def __init__(self, config: BrowserAgentConfig = DEFAULT_CONFIG) -> None:
        self._config = config
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    @property
    def is_alive(self) -> bool:
        return self._context is not None and self._page is not None

    async def start(self) -> None:
        """Launch the browser and open an initial blank page."""
        from playwright.async_api import async_playwright

        self._config.ensure_profile_dir()
        logger.info(
            "browser_session_starting",
            profile=str(self._config.profile_dir),
            headless=self._config.headless,
        )

        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self._config.profile_dir),
            headless=self._config.headless,
            slow_mo=self._config.slow_mo_ms,
            args=["--no-first-run", "--no-default-browser-check"],
        )
        self._context.set_default_timeout(self._config.timeout_ms)

        # Reuse the first existing page or open a new one.
        if self._context.pages:
            self._page = self._context.pages[0]
        else:
            self._page = await self._context.new_page()

        logger.info("browser_session_started")

    async def get_page(self) -> Page:
        """Return the active page, starting the session if needed."""
        if not self.is_alive:
            await self.start()
        assert self._page is not None
        return self._page

    async def new_page(self) -> Page:
        """Open a new tab and make it the active page."""
        if not self.is_alive:
            await self.start()
        assert self._context is not None
        self._page = await self._context.new_page()
        return self._page

    async def stop(self) -> None:
        """Close the browser context and stop Playwright."""
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
            self._page = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

        logger.info("browser_session_stopped")


# --------------------------------------------------------------------------- #
# Module-level singleton                                                         #
# --------------------------------------------------------------------------- #

_session: BrowserSession | None = None


async def get_session(config: BrowserAgentConfig = DEFAULT_CONFIG) -> BrowserSession:
    """Return the global BrowserSession, creating it on first call."""
    global _session
    async with _lock:
        if _session is None or not _session.is_alive:
            _session = BrowserSession(config)
        return _session


async def get_page(config: BrowserAgentConfig = DEFAULT_CONFIG) -> Page:
    """Convenience helper — returns the active Playwright Page."""
    session = await get_session(config)
    return await session.get_page()


async def close_session() -> None:
    """Shut down the global browser session (call on agent exit)."""
    global _session
    async with _lock:
        if _session is not None:
            await _session.stop()
            _session = None
