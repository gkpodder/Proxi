import { type FormEvent } from 'react'

type CommandPanelProps = {
  isListening: boolean
  isBusy: boolean
  statusClass: string
  statusLabel: string
  statusHint: string
  inputValue: string
  sampleCommands: string[]
  onInputChange: (value: string) => void
  onListenToggle: () => void
  onSubmitCommand: (text: string) => void
}

const CommandPanel = ({
  isListening,
  isBusy,
  statusClass,
  statusLabel,
  statusHint,
  inputValue,
  sampleCommands,
  onInputChange,
  onListenToggle,
  onSubmitCommand,
}: CommandPanelProps) => {
  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    onSubmitCommand(inputValue)
  }

  return (
    <div className="center-left">
      <div className="mic-cluster">
        <button
          className={`mic-button ${isListening ? 'active' : ''}`}
          type="button"
          onClick={onListenToggle}
          aria-pressed={isListening}
          aria-label="Toggle listening"
          accessKey="l"
          aria-keyshortcuts="Alt+L"
          disabled={isBusy}
        >
          <span className="mic-core" aria-hidden="true" />
          <span className="mic-label">{isListening ? 'Stop' : 'Listen'}</span>
        </button>
        <div className="mic-status">
          <span className={`status-dot status-${statusClass}`} aria-hidden="true" />
          <div>
            <p className="status-title">{statusLabel}</p>
            <p className="status-caption">{statusHint}</p>
          </div>
        </div>
      </div>

      <form className="input-panel" onSubmit={handleSubmit}>
        <label htmlFor="command-input">Type a request</label>
        <div className="input-row">
          <input
            id="command-input"
            type="text"
            placeholder="Open calendar and read my next meeting"
            value={inputValue}
            onChange={(event) => onInputChange(event.target.value)}
            disabled={isBusy}
          />
          <button
            className="btn primary"
            type="submit"
            aria-label="Send command"
            disabled={isBusy || inputValue.trim().length === 0}
          >
            Send
          </button>
        </div>
        <p className="input-note">Press Enter to send. Captions stay visible.</p>
      </form>

      <div className="chip-row" aria-label="Suggested commands">
        {sampleCommands.map((command) => (
          <button
            key={command}
            className="btn chip"
            type="button"
            onClick={() => onSubmitCommand(command)}
            disabled={isBusy}
          >
            {command}
          </button>
        ))}
      </div>

      <div className="voice-parity">
        <span className="tag">Voice parity</span>
        <p>
          Listen, Stop, Undo, Confirm, Cancel, and Settings are available by voice.
        </p>
      </div>
    </div>
  )
}

export default CommandPanel
