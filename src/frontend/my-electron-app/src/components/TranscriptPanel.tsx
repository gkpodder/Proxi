import type { Message } from '../types'

type TranscriptPanelProps = {
  messages: Message[]
}

const TranscriptPanel = ({ messages }: TranscriptPanelProps) => (
  <div className="transcript-panel">
    <div className="panel-header transcript-header">
      <div>
        <h2>Transcript</h2>
        <p>Every response is mirrored for captioning.</p>
      </div>
      <div className="tag-stack">
        <span className="tag">Session 04</span>
        <span className="tag">Output: Voice + Text</span>
      </div>
    </div>

    <div className="transcript-list" aria-live="polite">
      {messages.map((message) => (
        <div key={message.id} className={`message ${message.role}`}>
          <div className="message-meta">
            <span className="message-role">
              {message.role === 'user'
                ? 'You'
                : message.role === 'assistant'
                  ? 'Proxi'
                  : 'System'}
            </span>
            {message.channel ? (
              <span className="message-channel">
                {message.channel === 'voice' ? 'Voice' : 'Typed'}
              </span>
            ) : null}
            <span className="message-time">{message.time}</span>
          </div>
          <p className="message-text">{message.text}</p>
        </div>
      ))}
    </div>
  </div>
)

export default TranscriptPanel
