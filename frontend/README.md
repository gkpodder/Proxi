# Proxi Frontend

A modern React-based web interface for the Proxi agent system.

## Features

- 💬 **Chat Interface**: Clean, intuitive chat window for user prompts and agent responses
- 📊 **Status Panel**: Real-time status updates showing what the agent is doing
- 🚀 **WebSocket Integration**: Live streaming of execution status and results
- 📱 **Responsive Design**: Works on desktop and tablet devices

## Architecture

The frontend consists of two main components:

### Backend (FastAPI Server)
- Located in `proxi/server/app.py`
- Handles WebSocket connections for real-time communication
- Runs the Proxi agent loop and streams status updates
- Serves the built React frontend

### Frontend (React + Vite)
- Located in `frontend/`
- Chat window component for messages
- Status panel component for execution tracking
- Built with TypeScript for type safety

## Quick Start

### Option 1: Using the startup script

```bash
# From project root
python proxi/server/run.py
```

This will:
1. Install frontend dependencies (if needed)
2. Start the FastAPI backend on http://localhost:8000
3. Start the React dev server on http://localhost:5173

### Option 2: Manual startup

Terminal 1 - Backend:
```bash
cd project_root
uv run uvicorn proxi.server.app:app --reload
```

Terminal 2 - Frontend:
```bash
cd frontend
npm install  # First time only
npm run dev
```

Then open http://localhost:5173 in your browser.

## Building for Production

```bash
cd frontend
npm run build
```

The built files will be in `frontend/dist/` and will be automatically served by the FastAPI server.

## API

### WebSocket: `/ws/execute`

Send a JSON request with the following format:

```json
{
  "prompt": "Your prompt here",
  "provider": "openai"
}
```

Receive status updates:

```json
{
  "type": "started|status|completed|error",
  "message": "Human readable message",
  "status": "Current status",
  "result": "Final result (on completion)",
  "tokens_used": 123,
  "turns": 5
}
```

## Development

### Adding new components

Place React components in `frontend/src/components/`

### Styling

CSS files are alongside their components. Using plain CSS with CSS modules pattern.

### TypeScript

All components use TypeScript for better type safety and IDE support.

## Troubleshooting

**Port 8000 already in use?**
```bash
# Change the port in proxi/server/run.py or use:
uv run uvicorn proxi.server.app:app --reload --port 8001
```

**Node modules not installing?**
```bash
cd frontend
npm clean-install
```

**Frontend not connecting to backend?**
- Check that backend is running on http://localhost:8000
- Open browser console (F12) to see WebSocket connection errors
- Check CORS settings in `proxi/server/app.py`

## Performance Tips

- The status panel updates in real-time via WebSocket
- Chat messages are virtualized for smooth scrolling
- CSS animations are GPU-accelerated
