#!/usr/bin/env python
"""Debug vision planning setup."""

import os
from proxi.cli.main import create_llm_client, setup_sub_agents, setup_tools

def main():
    print(f"OPENAI_API_KEY present: {bool(os.getenv('OPENAI_API_KEY'))}")
    print(f"OPENAI_API_KEY length: {len(os.getenv('OPENAI_API_KEY', ''))}")
    
    llm = create_llm_client()
    registry = setup_tools()
    sub_agents = setup_sub_agents(
        llm, 
        registry, 
        enable_vision_verification=True,
        max_vision_checks=6
    )
    
    # Get browser agent through registry
    browser_agent = sub_agents.registry.get('browser')
    
    print(f"\nBrowser agent: {browser_agent}")
    print(f"Vision planner: {browser_agent.vision_planner}")
    if browser_agent.vision_planner:
        print(f"Vision planner model: {browser_agent.vision_planner.model}")
        print(f"Vision planner enabled: {browser_agent.vision_planner.enabled}")
        print(f"Vision planner client: {browser_agent.vision_planner.client}")
    print(f"Use vision planning flag: {browser_agent.use_vision_planning}")

if __name__ == "__main__":
    main()
