import { useState, useRef, useEffect } from 'react'
import ChatWindow from './components/ChatWindow'
import StatusPanel from './components/StatusPanel'
import './App.css'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
}

interface StatusUpdate {
  type: 'started' | 'status' | 'completed' | 'error'
  message?: string
  status?: string
  result?: string
  error?: string
  tokens_used?: number
  turns?: number
}

function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [statusUpdates, setStatusUpdates] = useState<StatusUpdate[]>([])
  const wsRef = useRef<WebSocket | null>(null)

  const handleSendMessage = (userMessage: string) => {
    if (!userMessage.trim()) return

    // Add user message to chat
    const userMsg: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: userMessage
    }
    setMessages(prev => [...prev, userMsg])
    setIsLoading(true)
    setStatusUpdates([])

    // Connect WebSocket and send request
    connectAndSend(userMessage)
  }

  const connectAndSend = (prompt: string) => {
    // In development, Vite proxies /ws to the backend at localhost:8000
    // In production, the frontend is served by the backend on the same host
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = import.meta.env.DEV ? 'localhost:8000' : window.location.host
    const ws = new WebSocket(`${protocol}//${host}/ws/execute`)

    ws.onopen = () => {
      console.log('WebSocket connected')
      // Send the prompt
      ws.send(JSON.stringify({ prompt, provider: 'openai' }))
    }

    ws.onmessage = (event) => {
      const data: StatusUpdate = JSON.parse(event.data)
      console.log('Received:', data)

      // Add to status updates
      setStatusUpdates(prev => [...prev, data])

      // If completed or error, add to chat and stop loading
      if (data.type === 'completed') {
        const assistantMsg: Message = {
          id: Date.now().toString(),
          role: 'assistant',
          content: data.result || 'Completed'
        }
        setMessages(prev => [...prev, assistantMsg])
        setIsLoading(false)
        ws.close()
      } else if (data.type === 'error') {
        const errorMsg: Message = {
          id: Date.now().toString(),
          role: 'assistant',
          content: `Error: ${data.error}`
        }
        setMessages(prev => [...prev, errorMsg])
        setIsLoading(false)
        ws.close()
      }
    }

    ws.onerror = (error) => {
      console.error('WebSocket error:', error)
      setIsLoading(false)
      const errorMsg: Message = {
        id: Date.now().toString(),
        role: 'assistant',
        content: 'Connection error occurred'
      }
      setMessages(prev => [...prev, errorMsg])
    }

    ws.onclose = () => {
      console.log('WebSocket closed')
    }

    wsRef.current = ws
  }

  return (
    <div className="app-container">
      <div className="main-content">
        <ChatWindow messages={messages} isLoading={isLoading} onSendMessage={handleSendMessage} />
      </div>
      <div className="status-sidebar">
        <StatusPanel statusUpdates={statusUpdates} isLoading={isLoading} />
      </div>
    </div>
  )
}

export default App
