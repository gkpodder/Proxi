export type AgentReply = {
  reply: string
  needsApproval: boolean
}

export function getAgentReply(text: string): Promise<AgentReply>
