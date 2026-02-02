#!/usr/bin/env python
"""Main entry point for the Proxi server with Windows subprocess support.

This script ensures the Windows Proactor event loop policy is set BEFORE
Uvicorn creates any event loops, which is necessary for MCP subprocess
initialization to work on Windows.
"""

import asyncio
import sys

# CRITICAL: Set Windows subprocess policy BEFORE importing uvicorn
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "proxi.server.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
