import type { Theme } from '../types'

type TopBarProps = {
  theme: Theme
  statusLabel: string
  statusClass: string
  onToggleTheme: () => void
}

const TopBar = ({ theme, statusLabel, statusClass, onToggleTheme }: TopBarProps) => (
  <header className="top-bar">
    <div className="brand">
      <div className="brand-mark" aria-hidden="true" />
      <div className="brand-text">
        <p className="brand-title">Proxi</p>
        <p className="brand-subtitle">Voice-first desktop companion</p>
      </div>
    </div>
    <div className="top-actions">
      <div className={`status-pill status-${statusClass}`}>
        <span className={`status-dot status-${statusClass}`} aria-hidden="true" />
        {statusLabel}
      </div>
      <button
        className="btn ghost"
        type="button"
        onClick={onToggleTheme}
        accessKey="t"
        aria-keyshortcuts="Alt+T"
      >
        {theme === 'day' ? 'Night mode' : 'Day mode'}
      </button>
    </div>
  </header>
)

export default TopBar
