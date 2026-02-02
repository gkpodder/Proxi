"""
Quick integration test to verify browser agent is properly registered with proxi.
"""
import os

from proxi.agents.browser import BrowserAgent
from proxi.agents.registry import SubAgentRegistry
from proxi.agents.summarizer import SummarizerAgent
from proxi.llm.openai import OpenAIClient


def test_browser_agent_registration():
    """Test that browser agent can be registered alongside other agents."""
    print("🧪 Testing browser agent registration...")
    
    # Create registry
    registry = SubAgentRegistry()
    
    # Register browser agent
    browser_agent = BrowserAgent(
        headless=True,
        max_steps=20,
    )
    registry.register(browser_agent)
    print(f"  ✅ Registered browser agent: {browser_agent.name}")
    
    # Verify it's in registry
    retrieved = registry.get("browser")
    assert retrieved is not None, "Browser agent not found in registry"
    assert retrieved.name == "browser"
    print(f"  ✅ Browser agent retrieved from registry")
    
    # Test to_specs()
    specs = registry.to_specs()
    browser_spec = next((s for s in specs if s.name == "browser"), None)
    assert browser_spec is not None, "Browser spec not in registry specs"
    print(f"  ✅ Browser agent spec found in registry")
    print(f"     - Name: {browser_spec.name}")
    print(f"     - Description: {browser_spec.description[:80]}...")
    print(f"     - Input schema keys: {list(browser_spec.input_schema.keys())}")
    
    # Register multiple agents together (like in main.py)
    print("\n🧪 Testing multi-agent registration...")
    registry2 = SubAgentRegistry()
    
    # Create a mock LLM client
    api_key = os.getenv("OPENAI_API_KEY", "test-key")
    llm_client = OpenAIClient(api_key=api_key)
    
    # Register summarizer
    summarizer = SummarizerAgent(llm_client)
    registry2.register(summarizer)
    print(f"  ✅ Registered summarizer agent")
    
    # Register browser
    browser_agent2 = BrowserAgent(headless=True)
    registry2.register(browser_agent2)
    print(f"  ✅ Registered browser agent")
    
    # Verify both are accessible
    all_specs = registry2.to_specs()
    assert len(all_specs) == 2, f"Expected 2 agents, got {len(all_specs)}"
    agent_names = [spec.name for spec in all_specs]
    assert "browser" in agent_names
    assert "summarizer" in agent_names
    print(f"  ✅ Both agents available: {agent_names}")
    
    print("\n✅ All registration tests passed!")
    return True


def test_browser_agent_initialization():
    """Test browser agent can be initialized with various configs."""
    print("\n🧪 Testing browser agent initialization...")
    
    # Test default config
    agent1 = BrowserAgent()
    assert agent1.name == "browser"
    assert agent1.headless == True
    assert agent1.max_steps == 20
    print(f"  ✅ Default config works")
    
    # Test custom config
    agent2 = BrowserAgent(
        headless=False,
        max_steps=50,
        allowed_domains=["example.com"],
        denied_domains=["bad.com"],
        artifacts_base_dir="./custom_dir",
    )
    assert agent2.headless == False
    assert agent2.max_steps == 50
    print(f"  ✅ Custom config works")
    
    # Test input schema
    schema = agent2.input_schema
    assert "properties" in schema
    assert "start_url" in schema["properties"]
    print(f"  ✅ Input schema is valid")
    
    print("\n✅ All initialization tests passed!")
    return True


def main():
    """Run all integration tests."""
    print("=" * 70)
    print("Browser Agent Integration Tests (without execution)")
    print("=" * 70)
    print()
    
    try:
        # Test 1: Initialization
        test_browser_agent_initialization()
        
        # Test 2: Registration
        test_browser_agent_registration()
        
        print("\n" + "=" * 70)
        print("✅ ALL INTEGRATION TESTS PASSED!")
        print("=" * 70)
        print()
        print("Next steps:")
        print("  1. Ensure playwright chromium is installed:")
        print("     playwright install chromium")
        print("  2. Run full browser test:")
        print("     python test_browser_integration.py")
        print("  3. Use browser agent in proxi:")
        print("     proxi 'Navigate to example.com and tell me the page title'")
        
        return True
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    import sys
    success = main()
    sys.exit(0 if success else 1)
