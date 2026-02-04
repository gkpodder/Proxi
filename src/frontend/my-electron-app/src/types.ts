export type Theme = 'day' | 'night'

export type Status = 'Idle' | 'Listening' | 'Processing' | 'Waiting'
export type Role = 'user' | 'assistant' | 'system'
export type Channel = 'voice' | 'text'

export type Message = {
  id: string
  role: Role
  text: string
  time: string
  channel?: Channel
}

export type ActivityStatus = 'Queued' | 'Running' | 'Needs confirmation' | 'Done' | 'Cancelled'

export type ActivityItem = {
  id: string
  title: string
  status: ActivityStatus
  time: string
}

export type PendingAction = {
  id: string
  title: string
}
