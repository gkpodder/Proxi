"""Native browser automation tools backed by Playwright."""

from __future__ import annotations

import base64
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from proxi.tools.base import BaseTool, ToolResult
from proxi.tools.browser_smart import SmartElementFinder, ObstacleDetector

logger = logging.getLogger(__name__)


class BrowserSessionManager:
    """Manage shared Playwright browser contexts/pages by session id."""

    def __init__(
        self,
        artifacts_root: Path,
        *,
        headless: bool = True,
        default_timeout_ms: int = 15_000,
    ) -> None:
        self.artifacts_root = artifacts_root
        self.headless = headless
        self.default_timeout_ms = default_timeout_ms

        self._playwright: Any | None = None
        self._browser: Any | None = None
        self._contexts: dict[str, Any] = {}
        self._pages: dict[str, Any] = {}

    async def _ensure_browser(self) -> None:
        if self._browser is not None:
            return

        try:
            from playwright.async_api import async_playwright
        except Exception as e:
            raise RuntimeError(
                "Playwright is not installed. Run `uv sync` and "
                "`uv run playwright install chromium`."
            ) from e

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)

    async def get_page(self, session_id: str) -> Any:
        """Get or create a page for a session id."""
        safe_session = self._sanitize_session_id(session_id)
        if safe_session in self._pages:
            return self._pages[safe_session]

        await self._ensure_browser()
        assert self._browser is not None

        context = await self._browser.new_context(viewport={"width": 1366, "height": 768})
        page = await context.new_page()
        page.set_default_timeout(self.default_timeout_ms)

        self._contexts[safe_session] = context
        self._pages[safe_session] = page
        return page

    async def take_screenshot(
        self,
        session_id: str,
        *,
        full_page: bool = False,
        quality: int = 65,
    ) -> tuple[str, str]:
        """Capture screenshot and return (path, base64_jpeg)."""
        page = await self.get_page(session_id)
        safe_session = self._sanitize_session_id(session_id)

        out_dir = self.artifacts_root / safe_session
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = f"screenshot-{int(time.time() * 1000)}.jpg"
        file_path = out_dir / filename

        image_bytes = await page.screenshot(
            path=str(file_path),
            full_page=full_page,
            type="jpeg",
            quality=quality,
        )
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        return str(file_path), b64

    async def close_session(self, session_id: str) -> None:
        """Close a single session page/context."""
        safe_session = self._sanitize_session_id(session_id)
        page = self._pages.pop(safe_session, None)
        context = self._contexts.pop(safe_session, None)

        if page is not None:
            try:
                await page.close()
            except Exception:
                pass
        if context is not None:
            try:
                await context.close()
            except Exception:
                pass

    async def close_all(self) -> None:
        """Close all sessions and browser process."""
        for session_id in list(self._pages.keys()):
            await self.close_session(session_id)

        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    def _sanitize_session_id(self, session_id: str) -> str:
        if not session_id:
            return "default"
        return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in session_id)


class BrowserNavigateTool(BaseTool):
    """Navigate browser to a URL."""

    def __init__(self, manager: BrowserSessionManager):
        super().__init__(
            name="browser_navigate",
            description="Navigate browser session to a URL.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "default": "default"},
                    "url": {"type": "string"},
                    "wait_until": {
                        "type": "string",
                        "enum": ["load", "domcontentloaded", "networkidle", "commit"],
                        "default": "domcontentloaded",
                    },
                },
                "required": ["url"],
            },
        )
        self.manager = manager

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        session_id = str(arguments.get("session_id", "default"))
        url = str(arguments.get("url", "")).strip()
        wait_until = str(arguments.get("wait_until", "domcontentloaded"))

        if not url:
            return ToolResult(success=False, output="", error="Missing 'url'")

        try:
            page = await self.manager.get_page(session_id)
            response = await page.goto(url, wait_until=wait_until)
            status = response.status if response else None
            final_url = page.url
            logger.info(f"Navigated to {final_url} (status={status})")
            
            # Automatically detect and clear obstacles
            detector = ObstacleDetector(page)
            obstacle_result = await detector.detect_and_clear(timeout=3.0)
            
            obstacle_info = ""
            if obstacle_result["obstacles_found"]:
                cleared = obstacle_result["obstacles_cleared"]
                found = obstacle_result["obstacles_found"]
                obstacle_info = f" (cleared obstacles: {cleared})"
            
            return ToolResult(
                success=True,
                output=f"Navigated to {final_url} (status={status}){obstacle_info}",
                metadata={
                    "session_id": session_id,
                    "url": final_url,
                    "status": status,
                    "obstacles": obstacle_result,
                },
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class BrowserClickTool(BaseTool):
    """Click an element by selector or visible text."""

    def __init__(self, manager: BrowserSessionManager):
        super().__init__(
            name="browser_click",
            description="Click an element in current browser page.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "default": "default"},
                    "selector": {"type": "string"},
                    "text": {"type": "string"},
                    "timeout_ms": {"type": "integer", "default": 10_000},
                    "force": {"type": "boolean", "default": False},
                },
            },
        )
        self.manager = manager

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        session_id = str(arguments.get("session_id", "default"))
        selector = str(arguments.get("selector", "")).strip()
        text = str(arguments.get("text", "")).strip()
        timeout_ms = int(arguments.get("timeout_ms", 10_000))
        force = bool(arguments.get("force", False))

        if not selector and not text:
            return ToolResult(success=False, output="", error="Provide 'selector' or 'text'")

        try:
            page = await self.manager.get_page(session_id)
            selector = self._normalize_date_selector(selector)
            
            # Proactively check for and dismiss obstacles before attempting click
            detector = ObstacleDetector(page)
            obstacle_result = await detector.detect_and_clear(timeout=1.0)
            
            # Use SmartElementFinder for adaptive element location
            finder = SmartElementFinder(page)
            is_likely_css_selector = any(ch in selector for ch in ("#", ".", "[", "]", ":", ">", "="))
            intent = text if text else (f"element matching {selector}" if is_likely_css_selector else selector)
            hint = selector if selector else None
            
            locator, strategy = await finder.find(
                intent=intent,
                hint=hint,
                timeout=timeout_ms / 1000,
            )
            
            if not locator:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Could not find element: {intent}",
                    metadata={"session_id": session_id, "intent": intent, "hint": hint},
                )
            
            target = text if text else selector
            obstacles_cleared = obstacle_result.get("obstacles_cleared", [])

            try:
                await locator.click(timeout=timeout_ms, force=force)
            except Exception as e:
                error_msg = str(e)
                # If click blocked by obstacle, try clearing again and retry
                if "intercept" in error_msg.lower() or "obscured" in error_msg.lower():
                    logger.info(f"Click blocked by obstacle, attempting to clear and retry")
                    retry_obstacle_result = await detector.detect_and_clear(timeout=2.0)
                    if retry_obstacle_result.get("obstacles_cleared"):
                        # Try click again after clearing
                        await locator.click(timeout=timeout_ms, force=True)
                        obstacles_cleared.extend(retry_obstacle_result.get("obstacles_cleared", []))
                    else:
                        # Force click as last resort
                        await locator.click(timeout=timeout_ms, force=True)
                else:
                    # Other error, try force click
                    await locator.click(timeout=timeout_ms, force=True)

            output_msg = f"Clicked {target} (strategy: {strategy})"
            if obstacles_cleared:
                output_msg += f" [auto-cleared: {', '.join(obstacles_cleared)}]"
            
            return ToolResult(
                success=True,
                output=output_msg,
                metadata={
                    "session_id": session_id,
                    "target": target,
                    "strategy": strategy,
                    "obstacles_cleared": obstacles_cleared,
                    "url": page.url,
                },
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

    def _normalize_date_selector(self, selector: str) -> str:
        """Normalize stale data-date selectors to current year when clearly outdated."""
        if not selector:
            return selector

        match = re.search(r"data-date=['\"](\d{4})-(\d{2})-(\d{2})['\"]", selector)
        if not match:
            return selector

        year, month, day = match.groups()
        current_year = datetime.utcnow().year
        if int(year) < current_year:
            return selector.replace(f"{year}-{month}-{day}", f"{current_year}-{month}-{day}")
        return selector


class BrowserPressKeyTool(BaseTool):
    """Press a keyboard key in browser page (useful for submit/escape flows)."""

    def __init__(self, manager: BrowserSessionManager):
        super().__init__(
            name="browser_press_key",
            description="Press keyboard key in current browser page (e.g., Enter, Escape, Tab).",
            parameters_schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "default": "default"},
                    "key": {"type": "string"},
                },
                "required": ["key"],
            },
        )
        self.manager = manager

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        session_id = str(arguments.get("session_id", "default"))
        key = str(arguments.get("key", "")).strip()

        if not key:
            return ToolResult(success=False, output="", error="Missing 'key'")

        try:
            page = await self.manager.get_page(session_id)
            await page.keyboard.press(key)
            return ToolResult(
                success=True,
                output=f"Pressed key: {key}",
                metadata={"session_id": session_id, "key": key, "url": page.url},
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class BrowserFillTool(BaseTool):
    """Fill an input field by selector."""

    def __init__(self, manager: BrowserSessionManager):
        super().__init__(
            name="browser_fill",
            description="Fill a text input field in browser page.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "default": "default"},
                    "selector": {"type": "string"},
                    "value": {"type": "string"},
                    "timeout_ms": {"type": "integer", "default": 10_000},
                },
                "required": ["selector", "value"],
            },
        )
        self.manager = manager

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        session_id = str(arguments.get("session_id", "default"))
        selector = str(arguments.get("selector", "")).strip()
        value = str(arguments.get("value", ""))
        timeout_ms = int(arguments.get("timeout_ms", 10_000))

        if not selector:
            return ToolResult(success=False, output="", error="Missing 'selector'")

        try:
            page = await self.manager.get_page(session_id)
            
            # Proactively check for obstacles before filling
            detector = ObstacleDetector(page)
            obstacle_result = await detector.detect_and_clear(timeout=1.0)
            
            # Use SmartElementFinder to locate input field
            finder = SmartElementFinder(page)
            is_likely_css_selector = any(ch in selector for ch in ("#", ".", "[", "]", ":", ">", "="))
            intent = f"input field {selector}" if is_likely_css_selector else selector
            locator, strategy = await finder.find(
                intent=intent,
                hint=selector,
                timeout=timeout_ms / 1000,
            )
            
            if not locator:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Could not find input field: {selector}",
                    metadata={"session_id": session_id, "selector": selector},
                )
            
            obstacles_cleared = obstacle_result.get("obstacles_cleared", [])
            
            # Clear existing value first, then fill
            try:
                await locator.clear(timeout=timeout_ms)
                await locator.fill(value, timeout=timeout_ms)
            except Exception as e:
                # If fill blocked, try clearing obstacles and retry
                error_msg = str(e)
                if "intercept" in error_msg.lower() or "obscured" in error_msg.lower():
                    logger.info(f"Fill blocked by obstacle, attempting to clear and retry")
                    retry_result = await detector.detect_and_clear(timeout=2.0)
                    if retry_result.get("obstacles_cleared"):
                        await locator.clear(timeout=timeout_ms)
                        await locator.fill(value, timeout=timeout_ms)
                        obstacles_cleared.extend(retry_result.get("obstacles_cleared", []))
                    else:
                        raise
                else:
                    raise
            
            # Verify the fill succeeded
            current = await locator.input_value()
            
            output_msg = f"Filled {selector} with '{value}' (strategy: {strategy})"
            if obstacles_cleared:
                output_msg += f" [auto-cleared: {', '.join(obstacles_cleared)}]"
            
            return ToolResult(
                success=current == value,
                output=output_msg,
                error=None if current == value else "Input value did not match expected value",
                metadata={
                    "session_id": session_id,
                    "selector": selector,
                    "strategy": strategy,
                    "value": current,
                    "obstacles_cleared": obstacles_cleared,
                    "url": page.url,
                    "verified": current == value,
                },
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class BrowserWaitForTool(BaseTool):
    """Wait for selector to appear."""

    def __init__(self, manager: BrowserSessionManager):
        super().__init__(
            name="browser_wait_for",
            description="Wait for an element selector in browser page.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "default": "default"},
                    "selector": {"type": "string"},
                    "timeout_ms": {"type": "integer", "default": 10_000},
                },
                "required": ["selector"],
            },
        )
        self.manager = manager

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        session_id = str(arguments.get("session_id", "default"))
        selector = str(arguments.get("selector", "")).strip()
        timeout_ms = int(arguments.get("timeout_ms", 10_000))

        if not selector:
            return ToolResult(success=False, output="", error="Missing 'selector'")

        try:
            page = await self.manager.get_page(session_id)

            selectors_to_try = [selector]
            url = page.url

            # Booking.com periodically changes result-card classes/test ids.
            if "booking.com" in url and any(k in selector for k in ("sr_property_block", "property_block", "hotel")):
                selectors_to_try.extend([
                    "[data-testid='property-card']",
                    "div[data-testid='property-card']",
                    "[data-testid='title']",
                    "[data-testid='property-card-container']",
                ])

            # Google News search result pages can use dynamic wrappers where
            # plain 'article' is not consistently visible.
            if "news.google.com" in url and selector.lower() in {"article", "h3", ".dy5t1d.rzikme"}:
                selectors_to_try.extend([
                    "main article",
                    "h3 a",
                    "a.DY5T1d",
                    "a.JtKRv",
                ])

            # De-duplicate while preserving order
            seen_sel: set[str] = set()
            deduped_selectors: list[str] = []
            for s in selectors_to_try:
                if s not in seen_sel:
                    seen_sel.add(s)
                    deduped_selectors.append(s)

            deadline = time.time() + (timeout_ms / 1000)
            last_error: Exception | None = None

            for idx, sel in enumerate(deduped_selectors):
                try:
                    remaining_ms_total = int(max(0, (deadline - time.time()) * 1000))
                    if remaining_ms_total <= 0:
                        break

                    selectors_left = max(1, len(deduped_selectors) - idx)
                    per_selector_timeout = max(3000, remaining_ms_total // selectors_left)

                    # Give dynamic pages a chance to settle before each attempt.
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=1_500)
                    except Exception:
                        pass
                    try:
                        await page.wait_for_load_state("networkidle", timeout=1_500)
                    except Exception:
                        pass

                    await self._wait_for_any_visible(page, sel, timeout_ms=per_selector_timeout)
                    selector = sel
                    last_error = None
                    break
                except Exception as e:
                    last_error = e
                    continue

            if last_error is not None:
                raise last_error

            return ToolResult(
                success=True,
                output=f"Element appeared: {selector}",
                metadata={
                    "session_id": session_id,
                    "selector": selector,
                    "selectors_tried": deduped_selectors,
                    "url": page.url,
                },
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

    async def _wait_for_any_visible(self, page: Page, selector: str, timeout_ms: int) -> None:
        """Wait until any matching element is visible (not just the first DOM match)."""
        end = time.time() + (timeout_ms / 1000)
        last_error: Exception | None = None

        while time.time() < end:
            try:
                locator = page.locator(selector)
                count = await locator.count()
                if count > 0:
                    # Check several candidates because many pages keep hidden first matches.
                    for i in range(min(count, 40)):
                        candidate = locator.nth(i)
                        try:
                            if await candidate.is_visible(timeout=200):
                                return
                        except Exception as e:
                            last_error = e
                            continue
            except Exception as e:
                last_error = e

            await page.wait_for_timeout(200)

        if last_error:
            raise last_error
        raise TimeoutError(f"Timeout {timeout_ms}ms exceeded while waiting for any visible match: {selector}")


class BrowserExtractTextTool(BaseTool):
    """Extract text from elements matching selector."""

    def __init__(self, manager: BrowserSessionManager):
        super().__init__(
            name="browser_extract_text",
            description="Extract visible text from browser page using CSS selector.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "default": "default"},
                    "selector": {"type": "string"},
                    "max_items": {"type": "integer", "default": 20},
                },
                "required": ["selector"],
            },
        )
        self.manager = manager

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        session_id = str(arguments.get("session_id", "default"))
        selector = str(arguments.get("selector", "")).strip()
        max_items = max(1, int(arguments.get("max_items", 20)))

        if not selector:
            return ToolResult(success=False, output="", error="Missing 'selector'")

        try:
            page = await self.manager.get_page(session_id)
            selectors_to_try = [selector]

            # Site-specific extraction helpers for news pages where generic tags
            # like "article" or "h3" often miss the actual headline links.
            is_google_news = "news.google.com" in page.url
            if is_google_news and selector.lower() in {"article", "h3", "headline", "headlines"}:
                selectors_to_try = [
                    "article h3 a",
                    "article h4 a",
                    "main article h3 a",
                    "main article h4 a",
                    "a.DY5T1d",
                    "a.JtKRv",
                    "h3 a",
                    "h4 a",
                    "article h3",
                    "article h4",
                    selector,
                ]

            texts: list[str] = []
            seen: set[str] = set()

            for sel in selectors_to_try:
                if len(texts) >= max_items:
                    break

                nodes = await page.query_selector_all(sel)
                for node in nodes:
                    if len(texts) >= max_items:
                        break

                    try:
                        # Prefer inner_text for rendered/visible copy.
                        txt = (await node.inner_text()).strip()
                    except Exception:
                        try:
                            # Fallback when node is detached/unrendered.
                            txt = (await node.text_content() or "").strip()
                        except Exception:
                            continue

                    if not txt:
                        continue

                    # Keep headlines concise and deduplicated.
                    txt = " ".join(txt.split())

                    # Google News pages often include section labels (e.g., Top stories)
                    # in heading tags; skip those when extracting article headlines.
                    if is_google_news:
                        generic_sections = {
                            "top stories",
                            "for you",
                            "local news",
                            "world",
                            "business",
                            "technology",
                            "entertainment",
                            "sports",
                            "science",
                            "health",
                        }
                        if txt.lower() in generic_sections:
                            continue

                    if txt in seen:
                        continue
                    seen.add(txt)
                    texts.append(txt)

            # Final fallback for Google News: scrape visible article anchor text
            # directly in-page when CSS-based extraction returns nothing.
            if is_google_news and not texts:
                try:
                    js_headlines = await page.evaluate(
                        """
                        () => {
                          const selectors = [
                            'a.DY5T1d',
                            'a.JtKRv',
                            'article h3 a',
                            'article h4 a',
                            'main article a[href*="./articles/"]',
                          ];

                          const out = [];
                          const seen = new Set();
                          for (const sel of selectors) {
                            const nodes = Array.from(document.querySelectorAll(sel));
                            for (const n of nodes) {
                              const t = (n.textContent || '').replace(/\s+/g, ' ').trim();
                              if (!t) continue;
                              const low = t.toLowerCase();
                              if (['top stories', 'for you', 'local news', 'world', 'business', 'technology', 'entertainment', 'sports', 'science', 'health'].includes(low)) continue;
                              if (seen.has(t)) continue;
                              seen.add(t);
                              out.push(t);
                              if (out.length >= 30) return out;
                            }
                          }
                          return out;
                        }
                        """
                    )
                    for t in js_headlines or []:
                        if len(texts) >= max_items:
                            break
                        if t not in seen:
                            seen.add(t)
                            texts.append(t)
                except Exception:
                    pass

            return ToolResult(
                success=True,
                output="\n".join(texts),
                metadata={
                    "session_id": session_id,
                    "selector": selector,
                    "count": len(texts),
                    "selectors_tried": selectors_to_try,
                    "url": page.url,
                },
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class BrowserScreenshotTool(BaseTool):
    """Capture a compressed screenshot for verification."""

    def __init__(self, manager: BrowserSessionManager):
        super().__init__(
            name="browser_screenshot",
            description="Take screenshot in current browser session for verification.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "default": "default"},
                    "full_page": {"type": "boolean", "default": False},
                },
            },
        )
        self.manager = manager

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        session_id = str(arguments.get("session_id", "default"))
        full_page = bool(arguments.get("full_page", False))

        try:
            file_path, image_b64 = await self.manager.take_screenshot(
                session_id,
                full_page=full_page,
                quality=65,
            )
            return ToolResult(
                success=True,
                output=f"Screenshot saved to {file_path}",
                metadata={
                    "session_id": session_id,
                    "path": file_path,
                    "image_base64": image_b64,
                },
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class BrowserAnalyzePageTool(BaseTool):
    """Analyze current page structure to discover interactive elements."""

    def __init__(self, manager: BrowserSessionManager):
        super().__init__(
            name="browser_analyze_page",
            description="Analyze current page structure to discover forms, buttons, inputs, and links.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "default": "default"},
                },
            },
        )
        self.manager = manager

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        session_id = str(arguments.get("session_id", "default"))

        try:
            page = await self.manager.get_page(session_id)
            
            # Extract semantic structure using accessibility tree and DOM inspection
            structure = {
                "url": page.url,
                "title": await page.title(),
                "forms": [],
                "buttons": [],
                "inputs": [],
                "links": [],
            }
            
            # Find all forms
            forms = await page.query_selector_all("form")
            for i, form in enumerate(forms[:5]):  # Limit to 5 forms
                form_id = await form.get_attribute("id")
                form_name = await form.get_attribute("name")
                form_action = await form.get_attribute("action")
                structure["forms"].append({
                    "index": i,
                    "id": form_id,
                    "name": form_name,
                    "action": form_action,
                })
            
            # Find all buttons
            buttons = await page.query_selector_all("button, input[type='button'], input[type='submit']")
            for i, button in enumerate(buttons[:10]):  # Limit to 10 buttons
                button_text = (await button.inner_text()).strip() if await button.inner_text() else ""
                button_type = await button.get_attribute("type")
                button_id = await button.get_attribute("id")
                button_name = await button.get_attribute("name")
                button_aria = await button.get_attribute("aria-label")
                is_visible = await button.is_visible()
                
                if is_visible or button_text or button_aria:
                    structure["buttons"].append({
                        "index": i,
                        "text": button_text,
                        "type": button_type,
                        "id": button_id,
                        "name": button_name,
                        "aria_label": button_aria,
                        "visible": is_visible,
                    })
            
            # Find all input fields
            inputs = await page.query_selector_all("input, textarea")
            for i, input_elem in enumerate(inputs[:15]):  # Limit to 15 inputs
                input_type = await input_elem.get_attribute("type")
                input_id = await input_elem.get_attribute("id")
                input_name = await input_elem.get_attribute("name")
                input_placeholder = await input_elem.get_attribute("placeholder")
                input_aria = await input_elem.get_attribute("aria-label")
                input_required = await input_elem.get_attribute("required")
                is_visible = await input_elem.is_visible()
                
                # Try to find associated label
                label_text = ""
                if input_id:
                    label = await page.query_selector(f"label[for='{input_id}']")
                    if label:
                        label_text = (await label.inner_text()).strip()
                
                if is_visible or input_placeholder or input_aria or label_text:
                    structure["inputs"].append({
                        "index": i,
                        "type": input_type,
                        "id": input_id,
                        "name": input_name,
                        "placeholder": input_placeholder,
                        "aria_label": input_aria,
                        "label": label_text,
                        "required": input_required is not None,
                        "visible": is_visible,
                    })
            
            # Find prominent links
            links = await page.query_selector_all("a[href]")
            for i, link in enumerate(links[:10]):  # Limit to 10 links
                link_text = (await link.inner_text()).strip()
                link_href = await link.get_attribute("href")
                link_aria = await link.get_attribute("aria-label")
                is_visible = await link.is_visible()
                
                if is_visible and (link_text or link_aria):
                    structure["links"].append({
                        "index": i,
                        "text": link_text,
                        "href": link_href,
                        "aria_label": link_aria,
                    })
            
            # Format output as readable summary
            output_lines = [
                f"Page: {structure['title']}",
                f"URL: {structure['url']}",
                f"\nForms: {len(structure['forms'])}",
            ]
            
            for form in structure["forms"]:
                form_desc = f"  Form {form['index']}"
                if form['id']:
                    form_desc += f" (id={form['id']})"
                if form['name']:
                    form_desc += f" (name={form['name']})"
                output_lines.append(form_desc)
            
            output_lines.append(f"\nButtons: {len(structure['buttons'])}")
            for btn in structure["buttons"][:5]:
                btn_desc = f"  Button: {btn['text'][:50]}"
                if btn['id']:
                    btn_desc += f" (id={btn['id']})"
                if btn['aria_label']:
                    btn_desc += f" (aria={btn['aria_label'][:30]})"
                output_lines.append(btn_desc)
            
            output_lines.append(f"\nInput Fields: {len(structure['inputs'])}")
            for inp in structure["inputs"][:5]:
                inp_desc = f"  {inp['type'] or 'input'}"
                if inp['label']:
                    inp_desc += f": {inp['label'][:40]}"
                elif inp['placeholder']:
                    inp_desc += f": {inp['placeholder'][:40]}"
                if inp['required']:
                    inp_desc += " (required)"
                if inp['id']:
                    inp_desc += f" [id={inp['id']}]"
                output_lines.append(inp_desc)
            
            return ToolResult(
                success=True,
                output="\n".join(output_lines),
                metadata={"session_id": session_id, "structure": structure},
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


def register_browser_tools(registry: Any, manager: BrowserSessionManager) -> None:
    """Register native browser tools into the given registry."""
    registry.register(BrowserNavigateTool(manager))
    registry.register(BrowserClickTool(manager))
    registry.register(BrowserFillTool(manager))
    registry.register(BrowserWaitForTool(manager))
    registry.register(BrowserExtractTextTool(manager))
    registry.register(BrowserScreenshotTool(manager))
    registry.register(BrowserPressKeyTool(manager))
    registry.register(BrowserAnalyzePageTool(manager))


def get_browser_session_manager(registry: Any) -> BrowserSessionManager | None:
    """Get attached BrowserSessionManager from tool registry."""
    manager = getattr(registry, "_browser_session_manager", None)
    return manager if isinstance(manager, BrowserSessionManager) else None
