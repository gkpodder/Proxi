/**
 * JSON-RPC message schemas for Python bridge <-> TUI communication.
 * One JSON object per line on stdin/stdout.
 */
import { z } from "zod";

// --- From Python to TUI ---

export const TextStreamSchema = z.object({
  type: z.literal("text_stream"),
  content: z.string(),
});
export type TextStream = z.infer<typeof TextStreamSchema>;

export const StatusUpdateSchema = z.object({
  type: z.literal("status_update"),
  label: z.string(),
  status: z.enum(["running", "done"]),
});
export type StatusUpdate = z.infer<typeof StatusUpdateSchema>;

export const UserInputRequiredSchema = z.object({
  type: z.literal("user_input_required"),
  method: z.enum(["select", "confirm", "text"]),
  options: z.array(z.string()).optional(),
  prompt: z.string().optional(),
});
export type UserInputRequired = z.infer<typeof UserInputRequiredSchema>;

export const ReadySchema = z.object({
  type: z.literal("ready"),
});
export type Ready = z.infer<typeof ReadySchema>;

export const BootCompleteSchema = z.object({
  type: z.literal("boot_complete"),
  agentId: z.string(),
  sessionId: z.string(),
});
export type BootComplete = z.infer<typeof BootCompleteSchema>;

export const BridgeMessageSchema = z.discriminatedUnion("type", [
  TextStreamSchema,
  StatusUpdateSchema,
  UserInputRequiredSchema,
  ReadySchema,
  BootCompleteSchema,
]);
export type BridgeMessage = z.infer<typeof BridgeMessageSchema>;

export function parseBridgeMessage(line: string): BridgeMessage | null {
  const trimmed = line.trim();
  if (!trimmed) return null;
  try {
    return BridgeMessageSchema.parse(JSON.parse(trimmed));
  } catch {
    return null;
  }
}

// --- From TUI to Python ---

export const StartTaskSchema = z.object({
  type: z.literal("start"),
  task: z.string(),
  provider: z.enum(["openai", "anthropic"]).optional(),
  maxTurns: z.number().optional(),
});
export type StartTask = z.infer<typeof StartTaskSchema>;

export const UserInputResponseSchema = z.object({
  type: z.literal("user_input"),
  value: z.union([z.string(), z.boolean(), z.number()]),
});
export type UserInputResponse = z.infer<typeof UserInputResponseSchema>;

export const SwitchAgentSchema = z.object({
  type: z.literal("switch_agent"),
});
export type SwitchAgent = z.infer<typeof SwitchAgentSchema>;

export const AbortSchema = z.object({
  type: z.literal("abort"),
});
export type Abort = z.infer<typeof AbortSchema>;

export const TuiToBridgeSchema = z.union([
  StartTaskSchema,
  UserInputResponseSchema,
  SwitchAgentSchema,
  AbortSchema,
]);
export type TuiToBridge = z.infer<typeof TuiToBridgeSchema>;

export function serializeTuiMessage(msg: TuiToBridge): string {
  return JSON.stringify(msg) + "\n";
}
