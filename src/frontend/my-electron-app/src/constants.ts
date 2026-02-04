import type { ActivityItem, Message, Status } from './types'

export const sampleCommands = [
  'Open calendar and read my next meeting',
  'Draft an email to my advisor about the demo',
  'Create a reminder to submit the report',
]

export const initialMessages: Message[] = [
  {
    id: 'm1',
    role: 'assistant',
    text: 'Welcome back. I am ready to help with your next task.',
    time: '09:12',
  },
  {
    id: 'm2',
    role: 'assistant',
    text: 'Speak or type a command. Responses are mirrored here for captioning.',
    time: '09:12',
  },
]

export const initialActivity: ActivityItem[] = []

export const statusLabels: Record<Status, string> = {
  Idle: 'Idle',
  Listening: 'Listening',
  Processing: 'Processing',
  Waiting: 'Awaiting confirmation',
}

export const statusHints: Record<Status, string> = {
  Idle: 'Ready for a command.',
  Listening: 'Say a request or click stop to cancel.',
  Processing: 'Planning the next steps.',
  Waiting: 'Confirmation required for a risky step.',
}
