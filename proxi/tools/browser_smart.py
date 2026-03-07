"""Smart browser automation helpers for adaptive element finding and obstacle handling."""

from __future__ import annotations

import asyncio
import logging
import inspect
import re
from typing import Any

from playwright.async_api import Page, Locator, TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger(__name__)


class SmartElementFinder:
    """Intelligent element finder with cascading fallback strategies."""
    
    def __init__(self, page: Page):
        self.page = page
    
    async def find(
        self,
        intent: str,
        hint: str | None = None,
        timeout: float = 10.0,
    ) -> tuple[Locator | None, str]:
        """
        Find an element using multiple strategies with fallbacks.
        
        Args:
            intent: What we're looking for (e.g., "search button", "email input")
            hint: Optional CSS selector hint from LLM
            timeout: Total timeout for all strategies
        
        Returns:
            Tuple of (Locator or None, strategy_used)
        """
        timeout_ms = int(timeout * 1000)
        
        # Define cascading strategies
        strategies = []
        
        # Strategy 1: Try provided hint first if available
        if hint:
            strategies.append(("css_hint", lambda: self.page.locator(hint)))

        # Strategy 1b: If hint/intent references a date, try robust data-date matches
        date_value = self._extract_date_value(hint or intent)
        if date_value:
            strategies.append(("data_date_exact", lambda: self.page.locator(f"[data-date='{date_value}']")))
            strategies.append(("data_date_button", lambda: self.page.locator(f"button[data-date='{date_value}']")))
            strategies.append(("data_date_cell", lambda: self.page.locator(f"td[data-date='{date_value}']")))
        
        # Strategy 2: For input fields, try common placeholder patterns
        if "input" in intent.lower():
            strategies.append(("placeholder_where", lambda: self.page.get_by_placeholder("Where", exact=False)))
            strategies.append(("placeholder_search", lambda: self.page.get_by_placeholder("Search", exact=False)))
            strategies.append(("placeholder_enter", lambda: self.page.get_by_placeholder("Enter", exact=False)))
        
        # Strategy 3: Try ARIA role-based selection
        strategies.append(("aria_role", lambda: self._try_aria_role(intent)))
        # Common explicit searchbox role (many sites expose this reliably)
        strategies.append(("searchbox_role", lambda: self.page.get_by_role("searchbox")))
        
        # Strategy 4: Try placeholder text (for inputs)
        strategies.append(("placeholder", lambda: self.page.get_by_placeholder(intent, exact=False)))
        
        # Strategy 5: Try label text (for inputs)
        strategies.append(("label", lambda: self.page.get_by_label(intent, exact=False)))
        
        # Strategy 6: Try exact text match
        strategies.append(("exact_text", lambda: self.page.get_by_text(intent, exact=True)))
        
        # Strategy 7: Try partial text match
        strategies.append(("partial_text", lambda: self.page.get_by_text(intent, exact=False)))
        
        # Strategy 8: Try common attribute patterns
        strategies.append(("attribute_pattern", lambda: self._try_attribute_pattern(intent)))
        
        # Strategy 9: Try XPath text search
        strategies.append(("xpath_text", lambda: self.page.locator(f"xpath=//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{intent.lower()}')]").first))
        
        # Strategy 10: For inputs, try finding first visible input of any type
        if "input" in intent.lower():
            strategies.append(("first_visible_input", lambda: self.page.locator("input[type='text'], input[type='search'], input:not([type])").first))
        
        # Try each strategy with timeout
        per_strategy_timeout = max(500, timeout_ms // len(strategies))
        
        for strategy_name, strategy_fn in strategies:
            try:
                strategy_result = strategy_fn()
                if inspect.isawaitable(strategy_result):
                    locator = await asyncio.wait_for(
                        strategy_result,
                        timeout=per_strategy_timeout / 1000,
                    )
                else:
                    locator = strategy_result
                
                if locator:
                    # Verify element exists and pick a visible actionable match.
                    # Many pages (e.g., weather/news/travel) keep hidden search inputs
                    # in headers or templates, so using `.first` is often brittle.
                    try:
                        count = await locator.count()
                        if count > 0:
                            visible_locator = await self._pick_visible_locator(locator, max_candidates=8)
                            if visible_locator is not None:
                                logger.info(f"Found element using strategy: {strategy_name}")
                                return visible_locator, strategy_name
                    except Exception as e:
                        logger.debug(f"Strategy {strategy_name} found element but visibility check failed: {e}")
                        continue
                        
            except (PlaywrightTimeoutError, asyncio.TimeoutError):
                logger.debug(f"Strategy {strategy_name} timed out")
                continue
            except Exception as e:
                logger.debug(f"Strategy {strategy_name} failed: {e}")
                continue
        
        logger.warning(f"All strategies failed to find element for intent: {intent}")
        return None, "none"

    def _extract_date_value(self, text: str | None) -> str | None:
        """Extract YYYY-MM-DD date from text/selectors when present."""
        if not text:
            return None
        m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
        return m.group(1) if m else None

    async def _pick_visible_locator(
        self,
        locator: Locator,
        max_candidates: int = 8,
    ) -> Locator | None:
        """Return the first visible locator from a locator list."""
        try:
            count = await locator.count()
            for i in range(min(count, max_candidates)):
                candidate = locator.nth(i)
                try:
                    await candidate.wait_for(state="visible", timeout=300)
                    return candidate
                except Exception:
                    continue
        except Exception:
            return None
        return None
    
    async def _try_aria_role(self, intent: str) -> Locator | None:
        """Try to find element by ARIA role."""
        intent_lower = intent.lower()
        
        # Map common intents to ARIA roles
        role_mappings = {
            "button": ["button"],
            "click": ["button", "link"],
            "submit": ["button"],
            "search": ["searchbox", "search"],
            "input": ["textbox"],
            "email": ["textbox"],
            "password": ["textbox"],
            "link": ["link"],
            "checkbox": ["checkbox"],
            "radio": ["radio"],
            "select": ["combobox", "listbox"],
            "menu": ["menu", "menubar"],
        }
        
        # Find matching roles
        roles_to_try = []
        for keyword, roles in role_mappings.items():
            if keyword in intent_lower:
                roles_to_try.extend(roles)
        
        if not roles_to_try:
            return None
        
        # Extract potential name from intent
        # E.g., "search button" -> try button with name containing "search"
        words = intent.split()
        name_hints = [w for w in words if w.lower() not in role_mappings]
        
        for role in roles_to_try:
            try:
                if name_hints:
                    # Try with name hint
                    for name_hint in name_hints:
                        locator = self.page.get_by_role(role, name=name_hint, exact=False)
                        if await locator.count() > 0:
                            return locator.first
                else:
                    # Try role without name
                    locator = self.page.get_by_role(role)
                    if await locator.count() > 0:
                        return locator.first
            except Exception:
                continue
        
        return None
    
    async def _try_attribute_pattern(self, intent: str) -> Locator | None:
        """Try common attribute patterns (id, name, class containing intent)."""
        intent_lower = intent.lower()
        intent_slug = intent_lower.replace(" ", "-")
        
        # Common patterns to try
        patterns = [
            f"[id*='{intent_slug}']",
            f"[name*='{intent_slug}']",
            f"[class*='{intent_slug}']",
            f"[data-test*='{intent_slug}']",
            f"[data-testid*='{intent_slug}']",
            f"[aria-label*='{intent}']",
        ]
        
        for pattern in patterns:
            try:
                locator = self.page.locator(pattern).first
                if await locator.count() > 0:
                    return locator
            except Exception:
                continue
        
        return None


class ObstacleDetector:
    """Detects and handles common web page obstacles (cookie banners, modals, etc)."""
    
    def __init__(self, page: Page):
        self.page = page
    
    async def detect_and_clear(self, timeout: float = 3.0) -> dict[str, Any]:
        """
        Detect and dismiss common obstacles on the page.
        
        Returns:
            Dict with keys: obstacles_found (list), obstacles_cleared (list), success (bool)
        """
        obstacles_found = []
        obstacles_cleared = []
        
        # Cookie banner patterns
        cookie_detected = await self._detect_obstacle(
            "cookie_banner",
            [
                "[id*='cookie']",
                "[class*='cookie']",
                "[id*='gdpr']",
                "[class*='gdpr']",
                "[id*='consent']",
                "[class*='consent']",
                ".cookie-notice",
                ".cookie-banner",
                "#onetrust-banner-sdk",
                "[class*='notice']",
                "[id*='notice']",
                "[aria-label*='cookie']",
                "[aria-label*='consent']",
            ],
            timeout=timeout / 3
        )
        
        if cookie_detected:
            obstacles_found.append("cookie_banner")
            if await self._dismiss_cookie_banner(timeout=timeout / 3):
                obstacles_cleared.append("cookie_banner")
        
        # Modal/dialog patterns
        modal_detected = await self._detect_obstacle(
            "modal",
            [
                "[role='dialog']",
                "[class*='modal']",
                "[class*='popup']",
                "[class*='overlay']",
                ".modal",
                ".popup",
                ".dialog",
                "[class*='lightbox']",
                "[id*='popup']",
                "[id*='modal']",
                "div[style*='z-index'][style*='fixed']",
                "div[style*='z-index'][style*='absolute']",
            ],
            timeout=timeout / 3
        )
        
        if modal_detected:
            obstacles_found.append("modal")
            if await self._dismiss_modal(timeout=timeout / 3):
                obstacles_cleared.append("modal")
        
        # Interstitial/splash screen patterns
        interstitial_detected = await self._detect_obstacle(
            "interstitial",
            [
                "[class*='interstitial']",
                "[class*='splash']",
                "[id*='interstitial']",
            ],
            timeout=timeout / 3
        )
        
        if interstitial_detected:
            obstacles_found.append("interstitial")
            if await self._dismiss_interstitial(timeout=timeout / 3):
                obstacles_cleared.append("interstitial")
        
        success = len(obstacles_found) == 0 or len(obstacles_cleared) > 0
        
        return {
            "obstacles_found": obstacles_found,
            "obstacles_cleared": obstacles_cleared,
            "success": success,
        }
    
    async def _detect_obstacle(
        self,
        obstacle_type: str,
        selectors: list[str],
        timeout: float
    ) -> bool:
        """Check if any of the selectors match visible elements."""
        timeout_ms = int(timeout * 1000)
        
        for selector in selectors:
            try:
                locator = self.page.locator(selector).first
                is_visible = await locator.is_visible(timeout=timeout_ms)
                if is_visible:
                    logger.info(f"Detected {obstacle_type} using selector: {selector}")
                    return True
            except Exception:
                continue
        
        return False
    
    async def _dismiss_cookie_banner(self, timeout: float) -> bool:
        """Try to dismiss cookie banner."""
        timeout_ms = int(timeout * 1000)
        
        # Common dismiss button patterns (try most common first)
        dismiss_patterns = [
            # Accept buttons (most common)
            "button:has-text('Accept')",
            "button:has-text('Accept all')",
            "button:has-text('I accept')",
            "button:has-text('Agree')",
            "button:has-text('OK')",
            "button:has-text('Got it')",
            "button:has-text('Allow')",
            "button:has-text('Allow all')",
            "button:has-text('Continue')",
            "[id*='accept']",
            "[class*='accept']",
            "[data-testid*='accept']",
            # Close buttons
            "button:has-text('×')",
            "button:has-text('✕')",
            "[aria-label*='Close']",
            "[aria-label*='close']",
            "button[aria-label*='close']",
            ".close-button",
            "[class*='close']:visible",
            "button.close",
            # Generic dismiss
            "[class*='dismiss']",
            "[id*='dismiss']",
        ]
        
        for pattern in dismiss_patterns:
            try:
                locator = self.page.locator(pattern).first
                if await locator.is_visible(timeout=500):  # Quick check
                    await locator.click(timeout=timeout_ms, force=True)
                    logger.info(f"Dismissed cookie banner using: {pattern}")
                    await asyncio.sleep(0.5)  # Wait for animation
                    return True
            except Exception as e:
                logger.debug(f"Failed to dismiss with pattern {pattern}: {e}")
                continue
        
        # Try pressing Escape as fallback
        try:
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(0.3)
            logger.info("Dismissed cookie banner with Escape key")
            return True
        except Exception:
            pass
        
        return False
    
    async def _dismiss_modal(self, timeout: float) -> bool:
        """Try to dismiss modal/dialog."""
        timeout_ms = int(timeout * 1000)
        
        dismiss_patterns = [
            # X buttons (most common)
            "button:has-text('×')",
            "button:has-text('✕')",
            "[class*='close']:visible",
            "[aria-label*='Close']",
            "[aria-label*='close']",
            "button[aria-label*='close']",
            "[class*='dismiss']",
            ".modal-close",
            ".popup-close",
            "button:has-text('Close')",
            "[data-dismiss='modal']",
            "[data-testid*='close']",
            # Sometimes there's a backdrop to click
            ".modal-backdrop",
            "[class*='overlay']:visible",
        ]
        
        for pattern in dismiss_patterns:
            try:
                locator = self.page.locator(pattern).first
                if await locator.is_visible(timeout=500):
                    await locator.click(timeout=timeout_ms, force=True)
                    logger.info(f"Dismissed modal using: {pattern}")
                    await asyncio.sleep(0.5)
                    return True
            except Exception:
                continue
        
        # Try Escape key
        try:
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(0.3)
            logger.info("Dismissed modal with Escape key")
            return True
        except Exception:
            pass
        
        return False
    
    async def _dismiss_interstitial(self, timeout: float) -> bool:
        """Try to dismiss interstitial/splash screen."""
        timeout_ms = int(timeout * 1000)
        
        dismiss_patterns = [
            "button:has-text('Continue')",
            "button:has-text('Skip')",
            "button:has-text('Close')",
            "[class*='skip']",
            "[class*='continue']",
        ]
        
        for pattern in dismiss_patterns:
            try:
                locator = self.page.locator(pattern).first
                if await locator.is_visible(timeout=timeout_ms):
                    await locator.click(timeout=timeout_ms, force=True)
                    logger.info(f"Dismissed interstitial using: {pattern}")
                    await asyncio.sleep(0.5)
                    return True
            except Exception:
                continue
        
        return False
