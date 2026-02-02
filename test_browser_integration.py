"""
Test script to verify browser agent integration with proxi.
"""
import asyncio
import os

from proxi.agents.browser import BrowserAgent
from proxi.agents.base import AgentContext


async def test_browser_agent():
    """Test browser agent with a simple task."""
    # Set up OpenAI API key (required for browser agent)
    if not os.getenv("OPENAI_API_KEY"):
        print("❌ OPENAI_API_KEY not set. Skipping browser agent test.")
        return

    print("🚀 Initializing browser agent...")
    
    # Create browser agent
    browser_agent = BrowserAgent(
        headless=True,
        max_steps=10,
        allowed_domains=[],
        denied_domains=[],
        artifacts_base_dir="./test_browser_artifacts",
    )
    
    print(f"✅ Browser agent initialized: {browser_agent.name}")
    print(f"   Description: {browser_agent.description}")
    
    # Create test context
    context = AgentContext(
        task="Navigate to example.com and extract the page title",
        context_refs={
            "start_url": "https://example.com",
        },
        history_snapshot=[],
    )
    
    print("\n🌐 Running browser task...")
    print(f"   Task: {context.task}")
    print(f"   Start URL: {context.context_refs.get('start_url')}")
    
    # Run browser agent
    try:
        result = await browser_agent.run(
            context=context,
            max_turns=10,
            max_tokens=2000,
            max_time=30.0,
        )
        
        print("\n📊 Results:")
        print(f"   Success: {result.success}")
        print(f"   Confidence: {result.confidence}")
        print(f"   Summary: {result.summary}")
        
        if result.artifacts:
            print(f"\n   Artifacts:")
            print(f"     - Final URL: {result.artifacts.get('final_url')}")
            print(f"     - Steps taken: {result.artifacts.get('steps_taken')}")
            print(f"     - Done: {result.artifacts.get('done')}")
            if result.artifacts.get('result_data'):
                print(f"     - Result data: {result.artifacts.get('result_data')}")
        
        if result.error:
            print(f"\n   ❌ Error: {result.error}")
        
        if result.follow_up_suggestions:
            print(f"\n   💡 Follow-up suggestions:")
            for suggestion in result.follow_up_suggestions:
                print(f"     - {suggestion}")
        
        print("\n✅ Browser agent test completed!")
        
    except Exception as e:
        print(f"\n❌ Browser agent test failed: {e}")
        raise


async def test_agent_spec():
    """Test that agent spec is generated correctly."""
    print("\n🔍 Testing agent spec generation...")
    
    browser_agent = BrowserAgent(
        headless=True,
        max_steps=20,
    )
    
    spec = browser_agent.to_spec()
    
    print(f"   Name: {spec['name']}")
    print(f"   Description: {spec['description']}")
    print(f"   Input schema: {spec['input_schema']}")
    
    print("✅ Agent spec test passed!")


async def main():
    """Main test runner."""
    print("=" * 60)
    print("Browser Agent Integration Test")
    print("=" * 60)
    
    # Test 1: Agent spec
    await test_agent_spec()
    
    # Test 2: Browser agent execution
    await test_browser_agent()
    
    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
