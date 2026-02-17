/**
 * Claude Code-style TUI for proxi agent.
 * - Scrollable chat, token streaming, dynamic status bar, HITL forms.
 * - Communicates with Python bridge via JSON-RPC over stdin/stdout.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Box, Text, useStdout } from "ink";
import { spawn, ChildProcess } from "node:child_process";
import path from "node:path";
import { parseBridgeMessage, serializeTuiMessage, type BridgeMessage, type UserInputRequired } from "./protocol.js";
import type { ChatMessage } from "./types.js";
import { ChatArea } from "./components/ChatArea.js";
import { InputArea } from "./components/InputArea.js";
import { StatusBar } from "./components/StatusBar.js";
import { HitlForm } from "./components/HitlForm.js";

type StatusKind = "tool" | "subagent" | "progress" | null;

function inferStatusKind(label: string | null, status: string): { kind: StatusKind; isProgress: boolean } {
  if (!label || status === "done") return { kind: null, isProgress: false };
  if (label.startsWith("Tool:")) return { kind: "tool", isProgress: true };
  if (label.includes("Subagent")) return { kind: "subagent", isProgress: true };
  return { kind: "progress", isProgress: true };
}

export default function App() {
  const { stdout } = useStdout();
  const [bridgeReady, setBridgeReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusLabel, setStatusLabel] = useState<string | null>(null);
  const [statusKind, setStatusKind] = useState<StatusKind>(null);
  const [isProgress, setIsProgress] = useState(false);
  const [inputValue, setInputValue] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState("");
  const [hitlSpec, setHitlSpec] = useState<UserInputRequired | null>(null);
  const [bootInfo, setBootInfo] = useState<{ agentId: string; sessionId: string } | null>(null);

  const childRef = useRef<ChildProcess | null>(null);
  const bufferRef = useRef("");
  const streamingRef = useRef("");

  useEffect(() => {
    const projectRoot = path.resolve(process.cwd(), "..");
    const env = {
      ...process.env,
      PYTHONUNBUFFERED: "1",
      PYTHONPATH: projectRoot,
    };

    const proc = spawn("uv run proxi-bridge", [], {
      stdio: ["pipe", "pipe", "pipe"],
      shell: true,
      cwd: projectRoot,
      env,
    });
    childRef.current = proc;

    proc.stdout?.setEncoding("utf8");
    proc.stderr?.setEncoding("utf8");

    proc.stdout?.on("data", (chunk: string) => {
      bufferRef.current += chunk;
      const lines = bufferRef.current.split("\n");
      bufferRef.current = lines.pop() ?? "";
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        const msg = parseBridgeMessage(trimmed);
        if (!msg) continue;
        handleMsg(msg);
      }
    });

    proc.stderr?.on("data", (data: string) => {
      const text = data.trim();
      if (text) setError((e) => e || text.slice(0, 150));
    });

    proc.on("error", (err) => {
      setError(`Bridge failed to start: ${err.message}`);
    });

    proc.on("exit", (code, signal) => {
      childRef.current = null;
      if (streamingRef.current) {
        setMessages((m) => [...m, { role: "assistant", content: streamingRef.current }]);
        setStreaming("");
        streamingRef.current = "";
      }
      if (code !== 0 && code !== null) {
        setError((e) => e || `Bridge exited with code ${code}. Set OPENAI_API_KEY and try again.`);
      }
      if (signal) setError((e) => e || `Bridge killed (${signal})`);
      setBridgeReady(false);
      setStatusLabel(null);
      setStatusKind(null);
      setIsProgress(false);
    });

    return () => {
      proc.kill();
      childRef.current = null;
    };
  }, []);

  function handleMsg(msg: BridgeMessage) {
    switch (msg.type) {
      case "ready":
        setBridgeReady(true);
        setError(null);
        break;
      case "boot_complete":
        setBootInfo({ agentId: msg.agentId, sessionId: msg.sessionId });
        break;
      case "text_stream":
        streamingRef.current += msg.content;
        setStreaming(streamingRef.current);
        break;
      case "status_update": {
        const { kind, isProgress: progress } = inferStatusKind(msg.label ?? null, msg.status);
        setStatusLabel(msg.status === "done" ? null : (msg.label ?? null));
        setStatusKind(msg.status === "done" ? null : kind);
        setIsProgress(progress && msg.status === "running");
        if (streamingRef.current) {
          setMessages((m) => [...m, { role: "assistant", content: streamingRef.current }]);
          setStreaming("");
          streamingRef.current = "";
        }
        break;
      }
      case "user_input_required":
        setHitlSpec(msg);
        break;
      default:
        break;
    }
  }

  const commitStreaming = useCallback(() => {
    if (streamingRef.current) {
      setMessages((m) => [...m, { role: "assistant", content: streamingRef.current }]);
      setStreaming("");
      streamingRef.current = "";
    }
  }, []);

  const onSwitchAgent = useCallback(() => {
    const proc = childRef.current;
    if (proc?.stdin?.writable) {
      proc.stdin.write(serializeTuiMessage({ type: "switch_agent" as const }));
    }
    // Clear current streaming buffer and note the switch in the chat log
    if (streamingRef.current) {
      setMessages((m) => [...m, { role: "assistant", content: streamingRef.current }]);
      setStreaming("");
      streamingRef.current = "";
    }
    setMessages((m) => [...m, { role: "system", content: "Switching agent..." }]);
  }, []);
  const onSubmit = useCallback((task: string, _provider: "openai" | "anthropic", _maxTurns: number) => {
    if (!task.trim()) return;
    setMessages((m) => [...m, { role: "user", content: task }]);
    setStreaming("");
    streamingRef.current = "";
    const proc = childRef.current;
    if (proc?.stdin?.writable) {
      proc.stdin.write(serializeTuiMessage({ type: "start", task }));
    }
  }, []);

  const onHitlSubmit = useCallback((value: string | boolean | number) => {
    const proc = childRef.current;
    if (proc?.stdin?.writable) {
      proc.stdin.write(serializeTuiMessage({ type: "user_input", value }));
    }
    setHitlSpec(null);
  }, []);

  const onHitlCancel = useCallback(() => {
    const proc = childRef.current;
    if (proc?.stdin?.writable) {
      proc.stdin.write(serializeTuiMessage({ type: "user_input", value: false }));
    }
    setHitlSpec(null);
  }, []);

  const minHeight = Math.max(8, (stdout.rows ?? 24) - 2);

  return (
    <Box flexDirection="column" paddingX={1} minHeight={minHeight}>
      <Box flexDirection="column" flexGrow={1} overflow="hidden" minHeight={6}>
        <ChatArea messages={messages} streamingContent={streaming} />
      </Box>

      <Box flexShrink={0} flexDirection="column">
        {error && (
          <Box marginBottom={0}>
            <Text color="red">{error}</Text>
          </Box>
        )}
        <StatusBar
          statusLabel={statusLabel}
          statusKind={statusKind}
          isProgress={isProgress}
        />
        {bootInfo && (
          <Box>
            <Text dimColor>
              Agent: {bootInfo.agentId} · Session: {bootInfo.sessionId}
            </Text>
          </Box>
        )}
        {hitlSpec ? (
          <HitlForm
            spec={hitlSpec}
            onSubmit={onHitlSubmit}
            onCancel={onHitlCancel}
          />
        ) : (
          <InputArea
            onSubmit={onSubmit}
            onCommitStreaming={commitStreaming}
            disabled={false}
            bridgeReady={bridgeReady}
            onSwitchAgent={onSwitchAgent}
          />
        )}
      </Box>
    </Box>
  );
}
