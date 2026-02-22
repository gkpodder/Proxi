/**
 * Zone A (scrollback) message formatting.
 * Pure ANSI output to stdout — no Ink.
 */
import { printLine, colors } from "./scrollback.js";

/** Format tool args for display: ToolName("arg") or ToolName({"key": "val"}) */
function formatToolInvocation(tool: string, args: Record<string, unknown> | undefined): string {
  if (!args || Object.keys(args).length === 0) {
    return `${tool}()`;
  }
  const entries = Object.entries(args);
  if (entries.length === 1) {
    const val = entries[0]![1];
    if (typeof val === "string" && val.length <= 80) {
      return `${tool}("${String(val).replace(/"/g, '\\"')}")`;
    }
  }
  const argsStr = JSON.stringify(args);
  if (argsStr.length <= 60) {
    return `${tool}(${argsStr})`;
  }
  return `${tool}(...)`;
}

export function printUserMessage(text: string): void {
  printLine(`  ${colors.purple(">")} ${colors.purple(text)}`);
}

export function printSpacing(): void {
  printLine("");
}

export function printAgentResponse(text: string): void {
  const lines = text.split("\n").filter((l) => l.length > 0);
  for (let i = 0; i < lines.length; i++) {
    const prefix = i === 0 ? "⏺" : " ";
    printLine(`  ${colors.white(prefix)} ${colors.white(lines[i] ?? "")}`);
  }
}

export function printAgentLine(line: string): void {
  printLine(`  ${colors.white("⏺")} ${colors.white(line)}`);
}

/** Streaming: buffer and print complete lines. Call commitAgentStream when done. */
let streamingBuffer = "";
let agentLineCount = 0;

export function appendAgentStream(chunk: string): void {
  streamingBuffer += chunk;
  const parts = streamingBuffer.split("\n");
  if (parts.length > 1) {
    const completed = parts.slice(0, -1);
    streamingBuffer = parts[parts.length - 1] ?? "";
    for (const line of completed) {
      if (line.length === 0) {
        printLine("");
      } else {
        const prefix = agentLineCount === 0 ? "⏺" : " ";
        printLine(`  ${colors.white(prefix)} ${colors.white(line)}`);
      }
      agentLineCount++;
    }
  }
}

export function commitAgentStream(): void {
  const lines = streamingBuffer.split("\n");
  streamingBuffer = "";
  for (const line of lines) {
    if (line.length === 0) {
      printLine("");
    } else {
      const prefix = agentLineCount === 0 ? "⏺" : " ";
      printLine(`  ${colors.white(prefix)} ${colors.white(line)}`);
    }
    agentLineCount++;
  }
  agentLineCount = 0; // Reset for next agent response
}

export function printToolStart(tool: string, args?: Record<string, unknown>): void {
  const invocation = formatToolInvocation(tool, args);
  printLine(`  ${colors.purpleDim("🛠️")}  ${colors.white(invocation)}`);
}

export function printToolLog(content: string): void {
  printLine(`  ${colors.mist("⎿")}  ${colors.mist(content)}`);
}

export function printToolDone(_tool: string, success: boolean, error?: string): void {
  if (success) {
    printLine(`  ${colors.mint("🛠️")}  ${colors.mint("✓ done")}`);
  } else {
    printLine(`  ${colors.rose("🛠️")}  ${colors.rose("✗ failed")}${error ? ` ${colors.rose(error)}` : ""}`);
  }
}

export function printSubagentStart(agent: string, _task: string): void {
  printLine(`  ${colors.purpleDim("🤖")}  ${colors.white(`sub-agent ${agent}`)} ${colors.purpleDim("⠋")} running...`);
}

export function printSubagentDone(agent: string, success: boolean): void {
  if (success) {
    printLine(`  ${colors.mint("🤖")}  ${colors.mint(`sub-agent ${agent} ✓ done`)}`);
  } else {
    printLine(`  ${colors.rose("🤖")}  ${colors.rose(`sub-agent ${agent} ✗ failed`)}`);
  }
}
