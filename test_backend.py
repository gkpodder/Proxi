#!/usr/bin/env python3
"""Quick test script to verify backend WebSocket connectivity."""

import asyncio
import json
import websockets

async def test_websocket():
    uri = "ws://localhost:8000/ws/execute"
    print(f"Connecting to {uri}...")
    
    try:
        async with websockets.connect(uri) as websocket:
            print("✓ Connected successfully!")
            
            # Send a test message
            test_message = {
                "prompt": "Say hello",
                "provider": "openai"
            }
            print(f"Sending: {test_message}")
            await websocket.send(json.dumps(test_message))
            
            # Wait for responses
            print("\nWaiting for responses...")
            async for message in websocket:
                data = json.loads(message)
                print(f"Received: {data.get('type', 'unknown')} - {data}")
                
                if data.get('type') in ['completed', 'error']:
                    print("\n✓ Test completed!")
                    break
                    
    except Exception as e:
        print(f"✗ Error: {e}")
        return False
    
    return True

if __name__ == "__main__":
    result = asyncio.run(test_websocket())
    exit(0 if result else 1)
