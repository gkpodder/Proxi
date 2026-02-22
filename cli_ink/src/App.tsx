/**
 * Claude Code-style TUI for proxi agent.
 * - Scrollable chat, token streaming, dynamic status bar, HITL forms.
 * - Communicates with Python bridge via JSON-RPC over stdin/stdout.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Box, Text, useStdout } from "ink";
import { spawn, ChildProcess } from "node:child_process";
import path from "node:path";
import {
  parseBridgeMessage,
  serializeTuiMessage,
  type BridgeMessage,
  type UserInputRequired,
  isCollaborativeFormRequired,
} from "./protocol.js";
import type { ScrollbackItem } from "./types/scrollback.js";
import { ScrollbackArea } from "./components/ScrollbackArea.js";
import { InputArea } from "./components/InputArea.js";
import { StatusBar } from "./components/StatusBar.js";
import { HitlForm } from "./components/HitlForm.js";
import { AnswerForm } from "./components/AnswerForm.js";
import { CommandPalette } from "./components/CommandPalette.js";
import { PlanTodosOverlay } from "./components/PlanTodosOverlay.js";

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
  const [hitlSpec, setHitlSpec] = useState<UserInputRequired | null>(null);
  const [bootInfo, setBootInfo] = useState<{ agentId: string; sessionId: string } | null>(null);
  const [scrollback, setScrollback] = useState<ScrollbackItem[]>([]);
  const [streamingContent, setStreamingContent] = useState("");
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [planTodosOverlay, setPlanTodosOverlay] = useState<"plan" | "todos" | null>(null);
  const [inputHistory, setInputHistory] = useState<string[]>([]);

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
        const lines = streamingRef.current.split("\n");
        const newItems: ScrollbackItem[] = [];
        let isFirst = true;
        for (const line of lines) {
          if (line.length === 0) newItems.push({ type: "agent_blank" });
          else {
            newItems.push({ type: "agent_line", content: line, isFirst });
            isFirst = false;
          }
        }
        setScrollback((s) => [...s, ...newItems]);
        setStreamingContent("");
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

  const commitStreamToScrollback = useCallback(() => {
    if (streamingRef.current) {
      const lines = streamingRef.current.split("\n");
      const newItems: ScrollbackItem[] = [];
      let isFirst = true;
      // Skip leading empty lines to reduce prompt-to-response spacing
      let i = 0;
      while (i < lines.length && lines[i]!.length === 0) i++;
      for (; i < lines.length; i++) {
        const line = lines[i]!;
        if (line.length === 0) newItems.push({ type: "agent_blank" });
        else {
          newItems.push({ type: "agent_line", content: line, isFirst });
          isFirst = false;
        }
      }
      setScrollback((s) => [...s, ...newItems]);
      setStreamingContent("");
      streamingRef.current = "";
    }
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
        setStreamingContent(streamingRef.current);
        break;
      case "tool_start":
        commitStreamToScrollback();
        setScrollback((s) => [...s, { type: "tool_start", tool: msg.tool, args: msg.arguments }]);
        break;
      case "tool_log":
        setScrollback((s) => [...s, { type: "tool_log", content: msg.content }]);
        break;
      case "tool_done":
        setScrollback((s) => [
          ...s,
          { type: "tool_done", success: msg.success, error: msg.error },
        ]);
        break;
      case "subagent_start":
        commitStreamToScrollback();
        setScrollback((s) => [...s, { type: "subagent", agent: msg.agent, status: "running" }]);
        break;
      case "subagent_done":
        setScrollback((s) => {
          const idx = [...s].reverse().findIndex(
            (i) => i.type === "subagent" && i.status === "running" && i.agent === msg.agent
          );
          if (idx === -1) {
            return [...s, { type: "subagent" as const, agent: msg.agent, status: "done" as const, success: msg.success }];
          }
          const i = s.length - 1 - idx;
          const next = [...s];
          next[i] = { type: "subagent", agent: msg.agent, status: "done", success: msg.success };
          return next;
        });
        break;
      case "status_update": {
        const { kind, isProgress: progress } = inferStatusKind(msg.label ?? null, msg.status);
        setStatusLabel(msg.status === "done" ? null : (msg.label ?? null));
        setStatusKind(msg.status === "done" ? null : kind);
        setIsProgress(progress && msg.status === "running");
        commitStreamToScrollback();
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
    commitStreamToScrollback();
  }, [commitStreamToScrollback]);

  const onSwitchAgent = useCallback(() => {
    const proc = childRef.current;
    if (proc?.stdin?.writable) {
      proc.stdin.write(serializeTuiMessage({ type: "switch_agent" as const }));
    }
    commitStreamToScrollback();
  }, [commitStreamToScrollback]);

  const onSubmit = useCallback((task: string, _provider: "openai" | "anthropic", _maxTurns: number) => {
    if (!task.trim()) return;
    setInputHistory((prev) => {
      const next = [task, ...prev.filter((t) => t !== task)].slice(0, 50);
      return next;
    });
    commitStreamToScrollback();
    setScrollback((s) => {
      const last = s[s.length - 1];
      const needsGap =
        last &&
        (last.type === "agent_line" ||
          last.type === "agent_blank" ||
          last.type === "tool_done" ||
          (last.type === "subagent" && last.status === "done"));
      const prefix = needsGap ? [{ type: "spacing" as const }] : [];
      return [...s, ...prefix, { type: "user", content: task }, { type: "spacing" as const }];
    });
    const proc = childRef.current;
    if (proc?.stdin?.writable) {
      proc.stdin.write(serializeTuiMessage({ type: "start", task }));
    }
  }, [commitStreamToScrollback]);

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

  const onAnswerFormSubmit = useCallback(
    (result: { tool_call_id: string; answers: Record<string, unknown>; skipped: boolean }) => {
      const proc = childRef.current;
      if (proc?.stdin?.writable) {
        proc.stdin.write(
          serializeTuiMessage({
            type: "user_input_response",
            payload: result,
          })
        );
      }
      setHitlSpec(null);
    },
    []
  );

  const onAbort = useCallback(() => {
    const proc = childRef.current;
    if (proc?.stdin?.writable) {
      proc.stdin.write(serializeTuiMessage({ type: "abort" as const }));
    }
    commitStreamToScrollback();
  }, [commitStreamToScrollback]);

  const onCommand = useCallback(
    (cmdId: string) => {
      switch (cmdId) {
        case "agent":
          onSwitchAgent();
          break;
        case "clear":
          setScrollback([]);
          break;
        case "plan":
          setPlanTodosOverlay("plan");
          break;
        case "todos":
          setPlanTodosOverlay("todos");
          break;
        case "help":
          setScrollback((s) => [
            ...s,
            { type: "agent_line", content: "/agent - Switch active agent", isFirst: true },
            { type: "agent_line", content: "/clear - Clear conversation", isFirst: false },
            { type: "agent_line", content: "/plan - View current plan", isFirst: false },
            { type: "agent_line", content: "/todos - View open todos", isFirst: false },
            { type: "agent_line", content: "/help - Show all commands", isFirst: false },
            { type: "agent_line", content: "/exit - Exit Proxi", isFirst: false },
          ]);
          break;
        case "exit":
          process.exit(0);
          break;
      }
    },
    [onSwitchAgent]
  );

  const minHeight = Math.max(8, (stdout?.rows ?? 24) - 4);

  return (
    <Box flexDirection="column" paddingX={1} minHeight={minHeight}>
      <ScrollbackArea items={scrollback} streamingContent={streamingContent} />
      <Box flexShrink={0} flexDirection="column" marginTop={1}>
        {error && (
          <Box marginBottom={0}>
            <Text color="red">{error}</Text>
          </Box>
        )}
        <StatusBar
          statusLabel={statusLabel}
          statusKind={statusKind}
          isProgress={isProgress}
          agentId={bootInfo?.agentId}
          sessionId={bootInfo?.sessionId}
          isWaitingForInput={!!hitlSpec}
        />
        {hitlSpec ? (
          isCollaborativeFormRequired(hitlSpec) ? (
            <AnswerForm
              payload={hitlSpec.payload}
              onSubmit={onAnswerFormSubmit}
            />
          ) : (
            <HitlForm
              spec={hitlSpec as import("./protocol.js").UserInputRequiredBootstrap}
              onSubmit={onHitlSubmit}
              onCancel={onHitlCancel}
            />
          )
        ) : commandPaletteOpen ? (
          <CommandPalette
            onDismiss={() => setCommandPaletteOpen(false)}
            onCommand={onCommand}
          />
        ) : planTodosOverlay && bootInfo ? (
          <PlanTodosOverlay
            type={planTodosOverlay}
            agentId={bootInfo.agentId}
            sessionId={bootInfo.sessionId}
            onDismiss={() => setPlanTodosOverlay(null)}
          />
        ) : (
          <InputArea
            onSubmit={onSubmit}
            onCommitStreaming={commitStreaming}
            disabled={isProgress}
            bridgeReady={bridgeReady}
            onSwitchAgent={onSwitchAgent}
            onAbort={onAbort}
            onOpenCommandPalette={() => setCommandPaletteOpen(true)}
            isRunning={isProgress}
            inputHistory={inputHistory}
          />
        )}
      </Box>
    </Box>
  );
}
