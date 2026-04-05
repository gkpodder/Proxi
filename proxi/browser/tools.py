"""Individual browser tools for Proxi.

These tools mirror the Hermes/Nous Research browser toolset and give the main
agent fine-grained, step-by-step control over a browser session.  All tools
share a single persistent BrowserContext (see session.py) backed by a
dedicated Chrome profile at ~/.proxi/browser_profile/.

All tools are registered in the *deferred* tier (heavy Playwright import only
on first use) and are not parallel-safe (browser state is mutable).

Tool list
---------
browser_navigate    Navigate to a URL
browser_click       Click an element by selector or visible text
browser_type        Type text into an input field
browser_scroll      Scroll the page
browser_snapshot    Get accessibility tree + URL (primary "observe" step)
browser_press       Press a keyboard key
browser_back        Navigate back in history
browser_close       Close the current page / session
browser_get_images  List all images on the current page
browser_console     Execute JavaScript and return the result
"""

from __future__ import annotations

import json
from typing import Any

from proxi.browser.session import close_session, get_page
from proxi.tools.base import BaseTool, ToolResult
from proxi.tools.registry import ToolRegistry


# --------------------------------------------------------------------------- #
# Helpers                                                                        #
# --------------------------------------------------------------------------- #


async def _safe_get_page() -> tuple[Any | None, str | None]:
    """Return (page, None) on success or (None, error_msg) on failure."""
    try:
        page = await get_page()
        return page, None
    except Exception as exc:
        return None, f"Failed to get browser page: {exc}"


def _tool_error(msg: str) -> ToolResult:
    return ToolResult(success=False, output="", error=msg)


# --------------------------------------------------------------------------- #
# browser_navigate                                                               #
# --------------------------------------------------------------------------- #


class BrowserNavigateTool(BaseTool):
    """Navigate the browser to a URL."""

    defer_loading = True

    def __init__(self) -> None:
        super().__init__(
            name="browser_navigate",
            description=(
                "Navigate the browser to a URL. "
                "Always call browser_snapshot after navigating to see the page state."
            ),
            parallel_safe=False,
            read_only=False,
            parameters_schema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Full URL to navigate to (include https://).",
                    },
                    "wait_until": {
                        "type": "string",
                        "enum": ["load", "domcontentloaded", "networkidle", "commit"],
                        "description": "When to consider navigation complete (default: load).",
                    },
                },
                "required": ["url"],
            },
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        url = arguments.get("url")
        if not url or not isinstance(url, str):
            return _tool_error("url argument is required")
        wait_until = str(arguments.get("wait_until", "load"))

        page, err = await _safe_get_page()
        if err:
            return _tool_error(err)

        try:
            response = await page.goto(url, wait_until=wait_until)  # type: ignore[arg-type]
            status = response.status if response else "unknown"
            return ToolResult(
                success=True,
                output=(
                    f"Navigated to {url} (HTTP {status}). "
                    "Call browser_snapshot to see the page."
                ),
                metadata={"url": page.url, "status": status},
            )
        except Exception as exc:
            return _tool_error(f"Navigation failed: {exc}")


# --------------------------------------------------------------------------- #
# browser_click                                                                  #
# --------------------------------------------------------------------------- #


class BrowserClickTool(BaseTool):
    """Click an element on the current page."""

    defer_loading = True

    def __init__(self) -> None:
        super().__init__(
            name="browser_click",
            description=(
                "Click an element on the current page. "
                "Use a CSS selector (e.g. '#submit'), Playwright text selector "
                "(e.g. 'text=Sign In'), or role selector (e.g. 'role=button[name=\"Buy\"]'). "
                "Call browser_snapshot first to find the right selector."
            ),
            parallel_safe=False,
            read_only=False,
            parameters_schema={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector, text= selector, or role= selector.",
                    },
                    "button": {
                        "type": "string",
                        "enum": ["left", "right", "middle"],
                        "description": "Mouse button to use (default: left).",
                    },
                    "double": {
                        "type": "boolean",
                        "description": "Double-click instead of single click.",
                    },
                },
                "required": ["selector"],
            },
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        selector = arguments.get("selector")
        if not selector or not isinstance(selector, str):
            return _tool_error("selector argument is required")
        button = str(arguments.get("button", "left"))
        double = bool(arguments.get("double", False))

        page, err = await _safe_get_page()
        if err:
            return _tool_error(err)

        try:
            locator = page.locator(selector)
            if double:
                await locator.dblclick(button=button)  # type: ignore[arg-type]
            else:
                await locator.click(button=button)  # type: ignore[arg-type]
            return ToolResult(
                success=True,
                output=f"Clicked '{selector}'.",
                metadata={"selector": selector, "url": page.url},
            )
        except Exception as exc:
            return _tool_error(f"Click failed: {exc}")


# --------------------------------------------------------------------------- #
# browser_type                                                                   #
# --------------------------------------------------------------------------- #


class BrowserTypeTool(BaseTool):
    """Type text into an input field."""

    defer_loading = True

    def __init__(self) -> None:
        super().__init__(
            name="browser_type",
            description=(
                "Type text into an input field or textarea. "
                "Set clear_first=true to clear the field before typing."
            ),
            parallel_safe=False,
            read_only=False,
            parameters_schema={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS/text/role selector for the input element.",
                    },
                    "text": {
                        "type": "string",
                        "description": "Text to type into the field.",
                    },
                    "clear_first": {
                        "type": "boolean",
                        "description": "Clear the field content before typing (default: true).",
                    },
                },
                "required": ["selector", "text"],
            },
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        selector = arguments.get("selector")
        text = arguments.get("text")
        if not selector or not isinstance(selector, str):
            return _tool_error("selector argument is required")
        if text is None:
            return _tool_error("text argument is required")
        clear_first = bool(arguments.get("clear_first", True))

        page, err = await _safe_get_page()
        if err:
            return _tool_error(err)

        try:
            locator = page.locator(selector)
            if clear_first:
                await locator.clear()
            await locator.type(str(text))
            return ToolResult(
                success=True,
                output=f"Typed into '{selector}'.",
                metadata={"selector": selector, "url": page.url},
            )
        except Exception as exc:
            return _tool_error(f"Type failed: {exc}")


# --------------------------------------------------------------------------- #
# browser_scroll                                                                 #
# --------------------------------------------------------------------------- #


class BrowserScrollTool(BaseTool):
    """Scroll the current page."""

    defer_loading = True

    def __init__(self) -> None:
        super().__init__(
            name="browser_scroll",
            description="Scroll the current page up, down, left, or right.",
            parallel_safe=False,
            read_only=False,
            parameters_schema={
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down", "left", "right"],
                        "description": "Direction to scroll.",
                    },
                    "amount": {
                        "type": "integer",
                        "description": "Pixels to scroll (default: 500).",
                    },
                },
                "required": ["direction"],
            },
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        direction = arguments.get("direction", "down")
        amount = int(arguments.get("amount", 500))

        page, err = await _safe_get_page()
        if err:
            return _tool_error(err)

        dx, dy = 0, 0
        if direction == "down":
            dy = amount
        elif direction == "up":
            dy = -amount
        elif direction == "right":
            dx = amount
        elif direction == "left":
            dx = -amount

        try:
            await page.evaluate(f"window.scrollBy({dx}, {dy})")
            return ToolResult(
                success=True,
                output=f"Scrolled {direction} by {amount}px.",
                metadata={"direction": direction, "amount": amount, "url": page.url},
            )
        except Exception as exc:
            return _tool_error(f"Scroll failed: {exc}")


# --------------------------------------------------------------------------- #
# browser_snapshot                                                               #
# --------------------------------------------------------------------------- #


class BrowserSnapshotTool(BaseTool):
    """Get the current page state as an accessibility tree.

    This is the primary 'observe' tool.  Call it after every navigate/click/type
    to understand what's on the page before deciding the next action.
    """

    defer_loading = True

    def __init__(self) -> None:
        super().__init__(
            name="browser_snapshot",
            description=(
                "Get the current browser page state: URL, title, and an "
                "accessibility tree of interactive elements (buttons, inputs, links, "
                "headings, text). Use this after every action to understand the page "
                "before deciding what to do next."
            ),
            parallel_safe=False,
            read_only=True,
            parameters_schema={
                "type": "object",
                "properties": {
                    "max_nodes": {
                        "type": "integer",
                        "description": "Maximum accessibility tree nodes to return (default: 200).",
                    },
                },
            },
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        max_nodes = int(arguments.get("max_nodes", 200))

        page, err = await _safe_get_page()
        if err:
            return _tool_error(err)

        try:
            url = page.url
            title = await page.title()

            # Build accessibility tree via Playwright's snapshot API.
            snapshot = await page.accessibility.snapshot(interesting_only=True)
            lines: list[str] = [
                f"URL: {url}",
                f"Title: {title}",
                "",
                "=== Accessibility Tree ===",
            ]
            _walk_snapshot(snapshot, lines, depth=0, counter=[0], max_nodes=max_nodes)

            output = "\n".join(lines)
            return ToolResult(
                success=True,
                output=output,
                metadata={"url": url, "title": title},
            )
        except Exception as exc:
            return _tool_error(f"Snapshot failed: {exc}")


def _walk_snapshot(
    node: dict[str, Any] | None,
    lines: list[str],
    depth: int,
    counter: list[int],
    max_nodes: int,
) -> None:
    if node is None or counter[0] >= max_nodes:
        return

    role = node.get("role", "")
    name = node.get("name", "")
    value = node.get("value", "")
    description = node.get("description", "")
    checked = node.get("checked")
    disabled = node.get("disabled", False)

    parts: list[str] = []
    if role:
        parts.append(f"[{role}]")
    if name:
        parts.append(f'"{name}"')
    if value:
        parts.append(f"value={value!r}")
    if description and description != name:
        parts.append(f"desc={description!r}")
    if checked is True:
        parts.append("(checked)")
    elif checked is False:
        parts.append("(unchecked)")
    if disabled:
        parts.append("(disabled)")

    if parts:
        indent = "  " * depth
        lines.append(f"{indent}{' '.join(parts)}")
        counter[0] += 1

    for child in node.get("children", []):
        _walk_snapshot(child, lines, depth + 1, counter, max_nodes)


# --------------------------------------------------------------------------- #
# browser_press                                                                  #
# --------------------------------------------------------------------------- #


class BrowserPressTool(BaseTool):
    """Press a keyboard key."""

    defer_loading = True

    def __init__(self) -> None:
        super().__init__(
            name="browser_press",
            description=(
                "Press a keyboard key on the current focused element or page. "
                "Examples: 'Enter', 'Tab', 'Escape', 'ArrowDown', 'Control+a'."
            ),
            parallel_safe=False,
            read_only=False,
            parameters_schema={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Key name (e.g. 'Enter', 'Tab', 'Escape', 'Control+a').",
                    },
                    "selector": {
                        "type": "string",
                        "description": "Optional: focus this element before pressing.",
                    },
                },
                "required": ["key"],
            },
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        key = arguments.get("key")
        if not key or not isinstance(key, str):
            return _tool_error("key argument is required")
        selector = arguments.get("selector")

        page, err = await _safe_get_page()
        if err:
            return _tool_error(err)

        try:
            if selector and isinstance(selector, str):
                await page.locator(selector).press(key)
            else:
                await page.keyboard.press(key)
            return ToolResult(
                success=True,
                output=f"Pressed key '{key}'.",
                metadata={"key": key, "url": page.url},
            )
        except Exception as exc:
            return _tool_error(f"Press failed: {exc}")


# --------------------------------------------------------------------------- #
# browser_back                                                                   #
# --------------------------------------------------------------------------- #


class BrowserBackTool(BaseTool):
    """Navigate back in browser history."""

    defer_loading = True

    def __init__(self) -> None:
        super().__init__(
            name="browser_back",
            description="Navigate back one step in the browser history.",
            parallel_safe=False,
            read_only=False,
            parameters_schema={"type": "object", "properties": {}},
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        page, err = await _safe_get_page()
        if err:
            return _tool_error(err)

        try:
            await page.go_back()
            return ToolResult(
                success=True,
                output=f"Navigated back. Current URL: {page.url}",
                metadata={"url": page.url},
            )
        except Exception as exc:
            return _tool_error(f"Back navigation failed: {exc}")


# --------------------------------------------------------------------------- #
# browser_close                                                                  #
# --------------------------------------------------------------------------- #


class BrowserCloseTool(BaseTool):
    """Close the current browser page and tear down the session."""

    defer_loading = True

    def __init__(self) -> None:
        super().__init__(
            name="browser_close",
            description=(
                "Close the current browser page and shut down the browser session. "
                "Call this when you are completely done with browser tasks."
            ),
            parallel_safe=False,
            read_only=False,
            parameters_schema={"type": "object", "properties": {}},
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            await close_session()
            return ToolResult(success=True, output="Browser session closed.")
        except Exception as exc:
            return _tool_error(f"Close failed: {exc}")


# --------------------------------------------------------------------------- #
# browser_get_images                                                             #
# --------------------------------------------------------------------------- #


class BrowserGetImagesTool(BaseTool):
    """List images on the current page."""

    defer_loading = True

    def __init__(self) -> None:
        super().__init__(
            name="browser_get_images",
            description=(
                "Return a list of all images on the current page with their src and alt text."
            ),
            parallel_safe=False,
            read_only=True,
            parameters_schema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max number of images to return (default: 20).",
                    },
                },
            },
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        limit = int(arguments.get("limit", 20))

        page, err = await _safe_get_page()
        if err:
            return _tool_error(err)

        try:
            images = await page.evaluate(
                """(limit) => {
                    const imgs = Array.from(document.querySelectorAll('img'));
                    return imgs.slice(0, limit).map(img => ({
                        src: img.src || img.getAttribute('src') || '',
                        alt: img.alt || '',
                        width: img.naturalWidth || img.width || 0,
                        height: img.naturalHeight || img.height || 0,
                    }));
                }""",
                limit,
            )
            output = json.dumps(images, indent=2)
            return ToolResult(
                success=True,
                output=output,
                metadata={"count": len(images), "url": page.url},
            )
        except Exception as exc:
            return _tool_error(f"Get images failed: {exc}")


# --------------------------------------------------------------------------- #
# browser_console                                                                #
# --------------------------------------------------------------------------- #


class BrowserConsoleTool(BaseTool):
    """Execute JavaScript in the browser console."""

    defer_loading = True

    def __init__(self) -> None:
        super().__init__(
            name="browser_console",
            description=(
                "Execute JavaScript in the browser page context and return the result. "
                "Useful for extracting data, reading DOM state, or triggering actions "
                "that are hard to do via clicks."
            ),
            parallel_safe=False,
            read_only=False,
            parameters_schema={
                "type": "object",
                "properties": {
                    "javascript": {
                        "type": "string",
                        "description": "JavaScript expression or statement to evaluate.",
                    },
                },
                "required": ["javascript"],
            },
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        js = arguments.get("javascript")
        if not js or not isinstance(js, str):
            return _tool_error("javascript argument is required")

        page, err = await _safe_get_page()
        if err:
            return _tool_error(err)

        try:
            result = await page.evaluate(js)
            output = json.dumps(result, indent=2, default=str)
            return ToolResult(
                success=True,
                output=output,
                metadata={"url": page.url},
            )
        except Exception as exc:
            return _tool_error(f"JavaScript execution failed: {exc}")


# --------------------------------------------------------------------------- #
# Registration helper                                                            #
# --------------------------------------------------------------------------- #

BROWSER_TOOL_CLASSES = [
    BrowserNavigateTool,
    BrowserClickTool,
    BrowserTypeTool,
    BrowserScrollTool,
    BrowserSnapshotTool,
    BrowserPressTool,
    BrowserBackTool,
    BrowserCloseTool,
    BrowserGetImagesTool,
    BrowserConsoleTool,
]


def register_browser_tools(registry: ToolRegistry) -> None:
    """Register all browser tools in the deferred tier of the given registry."""
    for cls in BROWSER_TOOL_CLASSES:
        registry.register_deferred(cls())
