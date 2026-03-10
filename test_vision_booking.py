#!/usr/bin/env python
"""Test vision planning with Booking.com"""

import asyncio
import os
from pathlib import Path
from proxi.cli.main import create_llm_client, setup_sub_agents, setup_tools
from proxi.agents.base import AgentContext
from proxi.tools.browser import get_browser_session_manager

async def test_booking():
    print("=== Testing Vision-Guided Navigation on Booking.com ===\n")
    
    # Setup
    llm = create_llm_client()
    registry = setup_tools()
    sub_agents = setup_sub_agents(llm, registry, enable_vision_verification=True, max_vision_checks=6)
    browser_agent = sub_agents.registry.get('browser')
    
    print(f"Vision planning enabled: {browser_agent.use_vision_planning}")
    print(f"Vision planner model: {browser_agent.vision_planner.model}\n")
    
    # Progress hook to see what's happening
    events = []
    def progress_hook(event_data):
        events.append(event_data)
        event_type = event_data.get("event")
        
        if event_type == "browser_tool_call":
            tool = event_data.get("tool")
            args = event_data.get("arguments", {})
            print(f"  🔧 {tool}({args})")
        
        elif event_type == "browser_tool_done":
            success = event_data.get("success")
            error = event_data.get("error")
            if success:
                print(f"  ✅ Success")
            else:
                print(f"  ❌ Failed: {error}")
        
        elif event_type == "vision_guidance":
            print(f"\n  🔮 VISION AI GUIDANCE:")
            print(f"     Reasoning: {event_data.get('reasoning', '')}")
            print(f"     Suggested actions:")
            for i, action in enumerate(event_data.get('next_actions', []), 1):
                print(f"       {i}. {action.get('tool')}: {action.get('description')}")
                if action.get('text_hint'):
                    print(f"          text_hint: '{action.get('text_hint')}'")
            print()
    
    # Create context with progress hook
    ctx = AgentContext(
        task="Go to booking.com, search for hotels in Paris",
        artifacts={},
        metadata={"progress_hook": progress_hook}
    )
    
    # Run
    print("Running browser agent...\n")
    result = await browser_agent.run(
        ctx, 
        max_turns=8, 
        max_tokens=6000,
        max_time=90
    )
    
    print(f"\n=== Result ===")
    print(f"Success: {result.success}")
    print(f"Summary: {result.summary[:300]}")
    print(f"\nTotal events: {len(events)}")
    vision_events = [e for e in events if e.get('event') == 'vision_guidance']
    print(f"Vision guidance events: {len(vision_events)}")
    
    # Cleanup
    mgr = get_browser_session_manager()
    await mgr.cleanup_all()

if __name__ == "__main__":
    asyncio.run(test_booking())
