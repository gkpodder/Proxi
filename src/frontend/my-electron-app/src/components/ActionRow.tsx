type ActionRowProps = {
  hasPendingAction: boolean
  onUndo: () => void
  onConfirm: () => void
  onCancel: () => void
}

const ActionRow = ({ hasPendingAction, onUndo, onConfirm, onCancel }: ActionRowProps) => (
  <div className="action-row">
    <button
      className="btn outline"
      type="button"
      onClick={onUndo}
      accessKey="u"
      aria-keyshortcuts="Alt+U"
    >
      Undo
    </button>
    <button
      className="btn primary"
      type="button"
      onClick={onConfirm}
      accessKey="c"
      aria-keyshortcuts="Alt+C"
      disabled={!hasPendingAction}
    >
      Confirm
    </button>
    <button
      className="btn outline"
      type="button"
      onClick={onCancel}
      accessKey="x"
      aria-keyshortcuts="Alt+X"
      disabled={!hasPendingAction}
    >
      Cancel
    </button>
    <button className="btn ghost" type="button" accessKey="s" aria-keyshortcuts="Alt+S">
      Settings
    </button>
  </div>
)

export default ActionRow
