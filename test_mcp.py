"""Quick test of MCP server Gmail integration."""
import asyncio
import json
import sys

async def test_mcp():
    """Test MCP server by sending requests."""
    from proxi.mcp.client import MCPClient
    
    client = MCPClient(["python", "-m", "proxi.mcp.servers.unified_server", "--enable-gmail"])
    
    try:
        # Initialize
        print("Initializing MCP client...")
        result = await client.initialize()
        print(f"✓ Initialized: {result}")
        
        # List tools
        print("\nListing tools...")
        tools = await client.list_tools()
        print(f"✓ Found {len(tools)} tools:")
        for tool in tools:
            print(f"  - {tool['name']}")
        
        # Try to call a Gmail tool
        print("\nCalling gmail_list_messages...")
        result = await client.call_tool("gmail_list_messages", {"max_results": 1})
        print(f"✓ Result: {json.dumps(result, indent=2)}")
        
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(test_mcp())
