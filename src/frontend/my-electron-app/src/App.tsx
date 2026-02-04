import { useEffect, useRef, useState } from 'react'
import './App.css'
import { getAgentReply } from './api/API'
import ActionRow from './components/ActionRow'
import ApprovalCard from './components/ApprovalCard'
import CommandPanel from './components/CommandPanel'
import TopBar from './components/TopBar'
import TranscriptPanel from './components/TranscriptPanel'
import {
  initialActivity,
  initialMessages,
  sampleCommands,
  statusHints,
  statusLabels,
} from './constants'
import type { ActivityItem, Channel, Message, PendingAction, Status, Theme } from './types'

function App() {
  const [theme, setTheme] = useState<Theme>('day')
  const [status, setStatus] = useState<Status>('Idle')
  const [inputValue, setInputValue] = useState('')
  const [messages, setMessages] = useState<Message[]>(initialMessages)
  const [activity, setActivity] = useState<ActivityItem[]>(initialActivity)
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null)
  const idRef = useRef(0)
  const listeningTimeoutRef = useRef<number | null>(null)

  const isBusy = status === 'Processing' || status === 'Waiting'
  const isListening = status === 'Listening'
  const statusClass = status.toLowerCase()
  const statusLabel = statusLabels[status]
  const statusHint = statusHints[status]

  const makeId = () => {
    idRef.current += 1
    return `${Date.now().toString(36)}-${idRef.current}`
  }

  const formatTime = (date = new Date()) =>
    date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })

  const clearListeningTimeout = () => {
    if (listeningTimeoutRef.current !== null) {
      window.clearTimeout(listeningTimeoutRef.current)
      listeningTimeoutRef.current = null
    }
  }

  const sendCommand = async (text: string, channel: Channel) => {
    if (isBusy) {
      return
    }

    clearListeningTimeout()

    const trimmed = text.trim()
    if (!trimmed) {
      return
    }

    const timestamp = formatTime()
    const actionId = makeId()

    setInputValue('')
    setMessages((prev) => [
      ...prev,
      {
        id: makeId(),
        role: 'user',
        text: trimmed,
        time: timestamp,
        channel,
      },
    ])
    setActivity((prev) =>
      [{ id: actionId, title: trimmed, status: 'Running', time: timestamp }, ...prev].slice(
        0,
        6,
      ),
    )
    setStatus('Processing')

    const { reply, needsApproval } = await getAgentReply(trimmed)
    const replyTime = formatTime()

    setMessages((prev) => [
      ...prev,
      {
        id: makeId(),
        role: 'assistant',
        text: reply,
        time: replyTime,
      },
    ])

    if (needsApproval) {
      setStatus('Waiting')
      setPendingAction({ id: actionId, title: trimmed })
      setActivity((prev) =>
        prev.map((item) =>
          item.id === actionId ? { ...item, status: 'Needs confirmation' } : item,
        ),
      )
      return
    }

    setStatus('Idle')
    setActivity((prev) =>
      prev.map((item) => (item.id === actionId ? { ...item, status: 'Done' } : item)),
    )
  }

  const handleListenToggle = () => {
    if (isListening) {
      clearListeningTimeout()
      setStatus('Idle')
      return
    }

    if (isBusy) {
      return
    }

    setStatus('Listening')
    const sample = sampleCommands[Math.floor(Math.random() * sampleCommands.length)]
    listeningTimeoutRef.current = window.setTimeout(() => {
      listeningTimeoutRef.current = null
      sendCommand(sample, 'voice')
    }, 900)
  }

  const handleConfirm = () => {
    if (!pendingAction) {
      return
    }

    const action = pendingAction
    setPendingAction(null)
    setStatus('Processing')
    setMessages((prev) => [
      ...prev,
      {
        id: makeId(),
        role: 'system',
        text: `Confirmed: ${action.title}`,
        time: formatTime(),
      },
    ])

    window.setTimeout(() => {
      setMessages((prev) => [
        ...prev,
        {
          id: makeId(),
          role: 'assistant',
          text: 'Confirmed. Action completed successfully.',
          time: formatTime(),
        },
      ])
      setActivity((prev) =>
        prev.map((item) => (item.id === action.id ? { ...item, status: 'Done' } : item)),
      )
      setStatus('Idle')
    }, 800)
  }

  const handleCancel = () => {
    if (!pendingAction) {
      return
    }

    const action = pendingAction
    setPendingAction(null)
    setStatus('Idle')
    setActivity((prev) =>
      prev.map((item) =>
        item.id === action.id ? { ...item, status: 'Cancelled' } : item,
      ),
    )
    setMessages((prev) => [
      ...prev,
      {
        id: makeId(),
        role: 'system',
        text: `Cancelled: ${action.title}`,
        time: formatTime(),
      },
    ])
  }

  const handleUndo = () => {
    if (activity.length === 0) {
      setMessages((prev) => [
        ...prev,
        { id: makeId(), role: 'system', text: 'Nothing to undo yet.', time: formatTime() },
      ])
      return
    }

    const latest = activity[0]
    setActivity((prev) =>
      prev.map((item, index) => (index === 0 ? { ...item, status: 'Cancelled' } : item)),
    )
    setMessages((prev) => [
      ...prev,
      {
        id: makeId(),
        role: 'system',
        text: `Undo requested for "${latest.title}".`,
        time: formatTime(),
      },
    ])

    if (pendingAction?.id === latest.id) {
      setPendingAction(null)
      setStatus('Idle')
    }
  }

  useEffect(() => () => clearListeningTimeout(), [])

  return (
    <div className={`app-shell ${theme === 'night' ? 'theme-night' : 'theme-day'}`}>
      <TopBar
        theme={theme}
        statusLabel={statusLabel}
        statusClass={statusClass}
        onToggleTheme={() => setTheme((prev) => (prev === 'day' ? 'night' : 'day'))}
      />

      <main className="main-grid">
        <section className="panel main-panel reveal reveal-1">
          <div className="panel-header">
            <div>
              <h2>Main Desktop Panel</h2>
              <p>Voice-first controls with keyboard and mouse support.</p>
            </div>
            <span className="tag">Input: Voice + Text</span>
          </div>

          <div className="center-grid">
            <CommandPanel
              isListening={isListening}
              isBusy={isBusy}
              statusClass={statusClass}
              statusLabel={statusLabel}
              statusHint={statusHint}
              inputValue={inputValue}
              sampleCommands={sampleCommands}
              onInputChange={setInputValue}
              onListenToggle={handleListenToggle}
              onSubmitCommand={(text) => sendCommand(text, 'text')}
            />
            <TranscriptPanel messages={messages} />
          </div>

          <ApprovalCard pendingAction={pendingAction} />

          <ActionRow
            hasPendingAction={Boolean(pendingAction)}
            onUndo={handleUndo}
            onConfirm={handleConfirm}
            onCancel={handleCancel}
          />
        </section>
      </main>
    </div>
  )
}

export default App
