#!/usr/bin/env python
"""Quick setup helper for Proxi frontend."""

import subprocess
import sys
from pathlib import Path

def main():
    """Print instructions for starting the frontend."""
    
    project_root = Path(__file__).parent
    
    print("\n" + "=" * 60)
    print("🚀 Proxi Frontend - Quick Start")
    print("=" * 60)
    
    print("\n📋 You need to run these commands in separate terminals:\n")
    
    print("Terminal 1 - Backend (from project root):")
    print("─" * 60)
    print("  uv run uvicorn proxi.server.app:app --reload --port 8000\n")
    
    print("Terminal 2 - Frontend:")
    print("─" * 60)
    print("  cd frontend")
    print("  npm install    # First time only")
    print("  npm run dev\n")
    
    print("=" * 60)
    print("Then open: http://localhost:5173 in your browser")
    print("=" * 60 + "\n")
    
    print("Want me to auto-install npm packages? (y/n): ", end="")
    response = input().strip().lower()
    
    if response == 'y':
        frontend_path = project_root / "frontend"
        if not (frontend_path / "node_modules").exists():
            print("\n📦 Installing frontend dependencies...")
            try:
                subprocess.run(
                    ["npm", "install"],
                    cwd=frontend_path,
                    check=True
                )
                print("✅ Frontend dependencies installed!\n")
            except FileNotFoundError:
                print("❌ npm not found. Please install Node.js from https://nodejs.org/")
                sys.exit(1)
            except subprocess.CalledProcessError as e:
                print(f"❌ Failed to install: {e}")
                sys.exit(1)
        else:
            print("✅ Dependencies already installed!\n")
    
    print("✅ Run the commands in separate terminals above!")

if __name__ == "__main__":
    main()

