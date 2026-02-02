"""Run proxi server with frontend."""

import subprocess
import sys
import time
import os
import shutil
from pathlib import Path

def find_npm():
    """Find npm executable, handling Windows properly."""
    # Try to find npm in PATH
    npm_path = shutil.which("npm")
    if npm_path:
        return npm_path
    
    # On Windows, try npm.cmd
    npm_cmd = shutil.which("npm.cmd")
    if npm_cmd:
        return npm_cmd
    
    raise FileNotFoundError("npm not found in PATH. Please install Node.js")

def main():
    """Start both backend server and frontend dev server."""
    
    # Get the project root
    project_root = Path(__file__).parent.parent.parent
    
    print("🚀 Starting Proxi Frontend & Backend")
    print("=" * 50)
    
    # Start FastAPI server
    print("\n📡 Starting backend server on http://localhost:8000")
    backend_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "proxi.server.app:app", "--reload"],
        cwd=project_root,
        env={**os.environ}
    )
    
    time.sleep(3)
    
    # Start frontend dev server
    print("🎨 Starting frontend on http://localhost:5173")
    frontend_path = project_root / "frontend"
    
    if not (frontend_path / "node_modules").exists():
        print("\n📦 Installing frontend dependencies...")
        npm = find_npm()
        try:
            subprocess.run(
                [npm, "install"],
                cwd=frontend_path,
                check=True
            )
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to install npm dependencies: {e}")
            backend_process.terminate()
            return
    
    npm = find_npm()
    frontend_process = subprocess.Popen(
        [npm, "run", "dev"],
        cwd=frontend_path,
    )
    
    print("\n✅ Both servers are running!")
    print("   Frontend: http://localhost:5173")
    print("   Backend:  http://localhost:8000")
    print("\nPress Ctrl+C to stop both servers")
    
    try:
        backend_process.wait()
        frontend_process.wait()
    except KeyboardInterrupt:
        print("\n\n🛑 Shutting down...")
        backend_process.terminate()
        frontend_process.terminate()
        try:
            backend_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            backend_process.kill()
        try:
            frontend_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            frontend_process.kill()
        print("✅ Shutdown complete")

if __name__ == "__main__":
    main()
