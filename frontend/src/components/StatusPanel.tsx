import './StatusPanel.css'

interface StatusUpdate {
  type: 'started' | 'status' | 'completed' | 'error'
  message?: string
  status?: string
  result?: string
  error?: string
  tokens_used?: number
  turns?: number
}

interface StatusPanelProps {
  statusUpdates: StatusUpdate[]
  isLoading: boolean
}

export default function StatusPanel({ statusUpdates, isLoading }: StatusPanelProps) {
  const latestStatus = statusUpdates[statusUpdates.length - 1]
  
  const getStatusColor = (type: string): string => {
    switch(type) {
      case 'started': return '#3b82f6'
      case 'status': return '#8b5cf6'
      case 'completed': return '#10b981'
      case 'error': return '#ef4444'
      default: return '#6b7280'
    }
  }

  const getStatusIcon = (type: string): string => {
    switch(type) {
      case 'started': return '🚀'
      case 'status': return '⚙️'
      case 'completed': return '✅'
      case 'error': return '❌'
      default: return 'ℹ️'
    }
  }

  return (
    <div className="status-panel">
      <h2>Status</h2>
      
      <div className="status-content">
        {isLoading && (
          <div className="loading-indicator">
            <div className="spinner"></div>
            <p>Processing...</p>
          </div>
        )}

        {statusUpdates.length === 0 && !isLoading && (
          <div className="empty-status">
            <p>No activity yet</p>
          </div>
        )}

        <div className="status-timeline">
          {statusUpdates.map((update, idx) => (
            <div 
              key={idx} 
              className="status-item"
              style={{ borderLeftColor: getStatusColor(update.type) }}
            >
              <span className="status-icon">{getStatusIcon(update.type)}</span>
              <div className="status-info">
                <p className="status-type">{update.type}</p>
                {update.message && <p className="status-message">{update.message}</p>}
                {update.status && <p className="status-message">{update.status}</p>}
              </div>
            </div>
          ))}
        </div>

        {latestStatus?.type === 'completed' && (
          <div className="completion-stats">
            <div className="stat">
              <span className="stat-label">Tokens Used:</span>
              <span className="stat-value">{latestStatus.tokens_used ?? 'N/A'}</span>
            </div>
            <div className="stat">
              <span className="stat-label">Turns:</span>
              <span className="stat-value">{latestStatus.turns ?? 'N/A'}</span>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
