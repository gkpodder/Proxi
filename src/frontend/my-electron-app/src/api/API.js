const fakeReplies = [
  'All set. I opened the panel and pulled your next two events.',
  'Draft ready. I highlighted key points for your review.',
  'Focus mode enabled. I will keep the transcript visible while you work.',
  'I found three relevant sections and summarized them.',
  'Reminder created with a 10 minute warning.',
]

const riskKeywords = ['delete', 'remove', 'erase', 'wipe', 'shutdown', 'format', 'revoke']

const buildMockReply = (text) => {
  const lower = text.toLowerCase()
  const needsApproval = riskKeywords.some((word) => lower.includes(word))

  if (needsApproval) {
    return {
      reply: `This request changes system data. Confirm to continue: "${text}".`,
      needsApproval: true,
    }
  }

  if (lower.includes('calendar')) {
    return {
      reply: 'Calendar is open. Next up: Project sync at 10:30 AM.',
      needsApproval: false,
    }
  }

  if (lower.includes('email')) {
    return {
      reply: 'Draft ready. I can open it for edits when you say so.',
      needsApproval: false,
    }
  }

  if (lower.includes('focus')) {
    return {
      reply: 'Focus mode is on for 25 minutes. Notifications are muted.',
      needsApproval: false,
    }
  }

  if (lower.includes('reminder')) {
    return {
      reply: 'Reminder created. I will notify you 10 minutes before.',
      needsApproval: false,
    }
  }

  return {
    reply: fakeReplies[Math.floor(Math.random() * fakeReplies.length)],
    needsApproval: false,
  }
}

export const getAgentReply = (text) =>
  new Promise((resolve) => {
    // TODO: Replace this mock with a real API integration.
    const delay = 700 + Math.random() * 600
    const response = buildMockReply(text)
    window.setTimeout(() => resolve(response), delay)
  })
