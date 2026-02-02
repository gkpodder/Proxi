"""
Example demonstrating how to use the browser sub-agent in proxi.

This shows how the main agent loop can delegate web browsing tasks
to the browser sub-agent.
"""
import asyncio
import os

from proxi.agents.base import AgentContext
from proxi.agents.browser import BrowserAgent


async def example_basic_browser_task():
    """Example: Simple web navigation and data extraction."""
    print("\n" + "=" * 70)
    print("Example 1: Basic Browser Task - Visit example.com")
    print("=" * 70)
    
    browser_agent = BrowserAgent(headless=True, max_steps=10)
    
    context = AgentContext(
        task="Navigate to example.com and extract the main heading",
        context_refs={
            "start_url": "https://example.com",
        },
        history_snapshot=[],
    )
    
    result = await browser_agent.run(context, max_turns=10, max_time=30.0)
    
    print(f"\n✅ Success: {result.success}")
    print(f"📊 Confidence: {result.confidence}")
    print(f"📝 Summary: {result.summary}")
    print(f"🎯 Result Data: {result.artifacts.get('result_data', {})}")


async def example_search_task():
    """Example: Search and extract results."""
    print("\n" + "=" * 70)
    print("Example 2: Search Task - Google search")
    print("=" * 70)
    
    browser_agent = BrowserAgent(
        headless=True,
        max_steps=15,
        allowed_domains=["google.com"],  # Restrict to Google
    )
    
    context = AgentContext(
        task="Search for 'Python programming' and extract the top 3 result titles",
        context_refs={
            "start_url": "https://www.google.com",
            "extract_fields": ["title", "url"],
        },
        history_snapshot=[
            {
                "role": "user",
                "content": "I need to research Python programming resources",
            },
        ],
    )
    
    result = await browser_agent.run(context, max_turns=15, max_time=45.0)
    
    print(f"\n✅ Success: {result.success}")
    print(f"📊 Confidence: {result.confidence}")
    print(f"📝 Summary: {result.summary}")
    
    if result.artifacts.get("result_data"):
        print(f"🎯 Extracted Data:")
        import json
        print(json.dumps(result.artifacts["result_data"], indent=2))


async def example_how_main_agent_uses_it():
    """
    Example: How the main agent loop would use browser sub-agent.
    
    This simulates what happens inside proxi's core loop when:
    1. The planner decides to use the browser sub-agent
    2. Context is built from the main agent's state
    3. The browser sub-agent is invoked
    4. Results are returned to the main agent
    """
    print("\n" + "=" * 70)
    print("Example 3: Main Agent -> Browser Sub-Agent Flow")
    print("=" * 70)
    
    # Step 1: Main agent receives user request
    user_request = "What is the capital of France? Look it up on Wikipedia."
    print(f"\n1️⃣ User request: {user_request}")
    
    # Step 2: Planner decides to use browser sub-agent
    print("\n2️⃣ Planner decides: Use 'browser' sub-agent")
    
    # Step 3: Build context for sub-agent
    print("\n3️⃣ Building context for browser sub-agent...")
    context = AgentContext(
        task="Navigate to Wikipedia and find the capital of France",
        context_refs={
            "start_url": "https://en.wikipedia.org/wiki/France",
            "extract_fields": ["capital"],
        },
        history_snapshot=[
            {"role": "user", "content": user_request},
            {"role": "assistant", "content": "I'll look that up on Wikipedia for you."},
        ],
    )
    
    # Step 4: Invoke browser sub-agent
    print("\n4️⃣ Invoking browser sub-agent...")
    browser_agent = BrowserAgent(
        headless=True,
        max_steps=10,
        allowed_domains=["wikipedia.org"],
    )
    
    result = await browser_agent.run(
        context=context,
        max_turns=10,
        max_tokens=2000,
        max_time=30.0,
    )
    
    # Step 5: Main agent receives result
    print("\n5️⃣ Browser sub-agent result received:")
    print(f"   Success: {result.success}")
    print(f"   Confidence: {result.confidence}")
    print(f"   Summary: {result.summary}")
    
    # Step 6: Main agent can use the artifacts
    print("\n6️⃣ Main agent processes artifacts:")
    print(f"   Final URL: {result.artifacts.get('final_url')}")
    print(f"   Steps taken: {result.artifacts.get('steps_taken')}")
    print(f"   Extracted data: {result.artifacts.get('result_data')}")
    
    # Step 7: Main agent responds to user
    if result.success and result.artifacts.get("result_data"):
        answer = result.artifacts["result_data"]
        print(f"\n7️⃣ Main agent responds to user:")
        print(f"   'According to Wikipedia: {answer}'")
    
    print("\n✅ Complete flow demonstrated!")


async def main():
    """Run all examples."""
    if not os.getenv("OPENAI_API_KEY"):
        print("❌ OPENAI_API_KEY not set. Please set it to run these examples.")
        print("   export OPENAI_API_KEY='your-key-here'")
        return
    
    print("=" * 70)
    print("Browser Sub-Agent Usage Examples")
    print("=" * 70)
    print()
    print("These examples show how the browser sub-agent integrates with proxi.")
    print("Note: These require playwright chromium to be installed:")
    print("  playwright install chromium")
    print()
    
    try:
        # Example 1: Basic usage
        await example_basic_browser_task()
        
        # Example 2: Search task (commented out to avoid rate limits)
        # await example_search_task()
        
        # Example 3: How main agent uses it
        await example_how_main_agent_uses_it()
        
        print("\n" + "=" * 70)
        print("✅ All examples completed!")
        print("=" * 70)
        
    except Exception as e:
        print(f"\n❌ Error running examples: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
