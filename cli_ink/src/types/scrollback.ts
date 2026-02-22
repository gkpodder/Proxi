/** Scrollback item types for Zone A (rendered via Ink Static) */
export type ScrollbackItem =
  | { type: "user"; content: string }
  | { type: "spacing" }
  | { type: "agent_line"; content: string; isFirst: boolean }
  | { type: "agent_blank" }
  | { type: "tool_start"; tool: string; args?: Record<string, unknown> }
  | { type: "tool_log"; content: string }
  | { type: "tool_done"; success: boolean; error?: string }
  | { type: "subagent"; agent: string; status: "running" }
  | { type: "subagent"; agent: string; status: "done"; success: boolean };
