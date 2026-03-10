"""Vision verification helper for browser actions (cheap-first, no escalation)."""

from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from proxi.observability.logging import get_logger

logger = get_logger(__name__)


class VisionPlanner:
    """Use vision AI to plan next browser actions by looking at screenshots."""
    
    def __init__(
        self,
        *,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
        enabled: bool = True,
    ) -> None:
        self.model = model
        self.enabled = enabled and bool(api_key)
        self.client = AsyncOpenAI(api_key=api_key) if self.enabled else None
        
        if enabled and not api_key:
            logger.warning("vision_planner_disabled_no_key")
    
    async def plan_next_actions(
        self,
        *,
        task: str,
        completed_actions: list[str],
        image_base64: str,
        page_url: str,
    ) -> dict[str, Any]:
        """
        Analyze screenshot and plan next concrete actions.
        
        Returns:
            {
                "next_actions": [
                    {
                        "tool": "browser_fill",
                        "description": "Fill search box with 'Paris'",
                        "selector_hint": "input visible in center with placeholder 'Where are you going?'",
                        "text_hint": "Where are you going",  # for text-based finding
                        "value": "Paris"  # for fill actions
                    },
                    {
                        "tool": "browser_click",
                        "description": "Click blue Search button",
                        "selector_hint": "button with text 'Search'",
                        "text_hint": "Search"
                    }
                ],
                "reasoning": "I see a search form...",
                "obstacles_visible": ["cookie banner at bottom"],
                "task_complete": false
            }
        """
        if not self.enabled or self.client is None:
            return {
                "next_actions": [],
                "reasoning": "Vision planner disabled",
                "task_complete": False,
            }
        
        completed_str = "\n".join(f"- {action}" for action in completed_actions[-5:]) if completed_actions else "None yet"
        
        prompt = (
            "You are a browser automation planner. Look at this webpage screenshot and plan the NEXT concrete actions needed.\n\n"
            "Return ONLY valid JSON with this structure:\n"
            "{\n"
            '  "next_actions": [\n'
            '    {\n'
            '      "tool": "browser_fill" | "browser_click" | "browser_extract_text" | "browser_press_key",\n'
            '      "description": "Human-readable what to do",\n'
            '      "text_hint": "Visible text to find element (for buttons/links)",\n'
            '      "selector_hint": "Describe element appearance/location for fallback",\n'
            '      "value": "text to fill" (only for browser_fill),\n'
            '      "key": "Enter|Escape" (only for browser_press_key)\n'
            '    }\n'
            '  ],\n'
            '  "reasoning": "What you see and why these actions",\n'
            '  "obstacles_visible": ["any popups/banners you see"],\n'
            '  "task_complete": false | true\n'
            "}\n\n"
            "CRITICAL: Be specific about visible text and element appearance. Use text_hint for buttons with visible text. "
            "Plan 1-3 actions maximum. If you see obstacles (cookie banner, modal), note them but DON'T plan to close them (automatic)."
        )
        
        user_text = (
            f"Task: {task}\n"
            f"Current URL: {page_url}\n"
            f"Completed actions:\n{completed_str}\n\n"
            "What should I do next? Look at the screenshot and plan concrete actions with specific element descriptions."
        )
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_text},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_base64}",
                                },
                            },
                        ],
                    },
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            
            raw = (response.choices[0].message.content or "{}").strip()
            parsed = self._safe_parse_json(raw)
            
            return {
                "next_actions": parsed.get("next_actions", []),
                "reasoning": parsed.get("reasoning", ""),
                "obstacles_visible": parsed.get("obstacles_visible", []),
                "task_complete": parsed.get("task_complete", False),
                "model": self.model,
            }
            
        except Exception as e:
            logger.warning("vision_planning_error", error=str(e))
            return {
                "next_actions": [],
                "reasoning": f"Planning failed: {e}",
                "task_complete": False,
            }
    
    def _safe_parse_json(self, text: str) -> dict[str, Any]:
        """Safely parse JSON from vision model response."""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            if "{" in text and "}" in text:
                start = text.index("{")
                end = text.rindex("}") + 1
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass
            return {}


class VisionVerifier:
    """Verify browser action outcomes with a vision model."""

    def __init__(
        self,
        *,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
        min_confidence: float = 0.55,
        enabled: bool = True,
    ) -> None:
        self.model = model
        self.min_confidence = min_confidence
        self.enabled = enabled and bool(api_key)
        self.client = AsyncOpenAI(api_key=api_key) if self.enabled else None

        if enabled and not api_key:
            logger.warning("vision_verifier_disabled_no_key")

    async def verify_action(
        self,
        *,
        task: str,
        session_id: str,
        turn: int,
        tool_name: str,
        arguments: dict[str, Any],
        observation: str,
        image_base64: str,
    ) -> dict[str, Any]:
        """Return structured verification result for a tool action."""
        if not self.enabled or self.client is None:
            return {
                "enabled": False,
                "verified": False,
                "confidence": 0.0,
                "passed": True,
                "reason": "Vision verifier disabled",
                "model": self.model,
            }

        prompt = (
            "You are validating whether a browser automation action succeeded. "
            "Use both screenshot and observation text. Return strict JSON only with keys: "
            "passed (boolean), confidence (0..1), reason (string), next_step_hint (string), "
            "error_type (string: selector_failed|element_obscured|wrong_page|timing_issue|success|unknown)."
        )

        user_text = (
            f"Task: {task}\n"
            f"Session: {session_id}\n"
            f"Turn: {turn}\n"
            f"Tool: {tool_name}\n"
            f"Arguments: {json.dumps(arguments, ensure_ascii=False)}\n"
            f"Observation: {observation[:1500]}\n"
            "Evaluate if the intended action likely succeeded. "
            "If uncertain, set passed=false with lower confidence and suggest a specific retry hint."
        )

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_text},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_base64}",
                                },
                            },
                        ],
                    },
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )
            raw = (response.choices[0].message.content or "{}").strip()
            parsed = self._safe_parse_json(raw)

            confidence = float(parsed.get("confidence", 0.0))
            passed = bool(parsed.get("passed", False))
            reason = str(parsed.get("reason", "No reason provided"))
            next_step_hint = str(parsed.get("next_step_hint", ""))
            error_type = str(parsed.get("error_type", "unknown"))

            verified_pass = passed and confidence >= self.min_confidence

            return {
                "enabled": True,
                "verified": True,
                "passed": verified_pass,
                "raw_passed": passed,
                "confidence": max(0.0, min(confidence, 1.0)),
                "reason": reason,
                "next_step_hint": next_step_hint,
                "error_type": error_type,
                "model": self.model,
            }
        except Exception as e:
            logger.warning("vision_verify_error", error=str(e), tool=tool_name)
            return {
                "enabled": True,
                "verified": False,
                "passed": True,
                "confidence": 0.0,
                "reason": f"Verification failed (non-blocking): {e}",
                "model": self.model,
            }

    def _safe_parse_json(self, text: str) -> dict[str, Any]:
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(text[start : end + 1])
                    return parsed if isinstance(parsed, dict) else {}
                except Exception:
                    return {}
            return {}
