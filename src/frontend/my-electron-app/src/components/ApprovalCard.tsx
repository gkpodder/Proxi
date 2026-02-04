import type { PendingAction } from '../types'

type ApprovalCardProps = {
  pendingAction: PendingAction | null
}

const ApprovalCard = ({ pendingAction }: ApprovalCardProps) => (
  <div className="approval-card">
    <div className="approval-header">
      <span className="approval-title">Pending confirmation</span>
      <span className={`status-dot status-${pendingAction ? 'waiting' : 'idle'}`} />
    </div>
    <p className="approval-body">
      {pendingAction
        ? `Awaiting confirmation for: ${pendingAction.title}`
        : 'No high-risk actions pending.'}
    </p>
    <p className="approval-note">Use the bottom row to confirm, cancel, or undo.</p>
  </div>
)

export default ApprovalCard
