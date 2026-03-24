/** Scrollback item types for Zone A (rendered via Ink Static) */
export type ScrollbackItem =
  | { type: "user"; content: string }
  /** Heartbeat, cron, webhook, … — shows source tag + prompt like user input. */
  | {
      type: "inbound_turn_header";
      sourceType: string;
      sourceId: string;
      prompt: string;
    }
  | { type: "spacing" }
  /** Model response text unless `isSystem` (local /commands, MCP UI, etc.). */
  | { type: "agent_line"; content: string; isFirst: boolean; isSystem?: boolean }
  | { type: "agent_blank" }
  | { type: "tool_start"; tool: string; args?: Record<string, unknown> }
  | { type: "tool_log"; content: string }
  | { type: "tool_done"; success: boolean; error?: string }
  | { type: "subagent"; agent: string; status: "running" }
  | { type: "subagent"; agent: string; status: "done"; success: boolean };
