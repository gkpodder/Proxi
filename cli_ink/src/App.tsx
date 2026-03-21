/**
 * Claude Code-style TUI for proxi agent.
 * - Scrollable chat, token streaming, dynamic status bar, HITL forms.
 * - Communicates with the gateway daemon via SSE + HTTP POST.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Box, Text, useInput, useStdout } from "ink";
import {
  parseBridgeMessage,
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

// Gateway URL from env, fallback to localhost:8765
const GATEWAY = process.env.PROXI_GATEWAY_URL || "http://localhost:8765";

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
  const [bootHint, setBootHint] = useState("Connecting to gateway...");
  const [userSendPending, setUserSendPending] = useState(false);
  const [tuiActiveDepth, setTuiActiveDepth] = useState(0);
  const [lastTuiAbortableStatus, setLastTuiAbortableStatus] = useState(false);

  const bootInfoRef = useRef<{ agentId: string; sessionId: string } | null>(null);
  bootInfoRef.current = bootInfo;

  const abortRef = useRef<AbortController | null>(null);
  const agentModeRef = useRef(false);
  const initialAgentPickRef = useRef(false);
  const bufferRef = useRef("");
  const streamingRef = useRef("");
  const overlayRef = useRef({ planTodosOverlay, commandPaletteOpen });
  overlayRef.current = { planTodosOverlay, commandPaletteOpen };

  // Resolved session_id (set from boot_complete)
  const sessionRef = useRef<string>("");
  const handleMsgRef = useRef<(msg: BridgeMessage) => void>(() => {});
  const onAbortRef = useRef<() => void>(() => {});

  useInput(
    (_, key) => {
      if (!key.escape) return;
      const { planTodosOverlay: plan, commandPaletteOpen: palette } = overlayRef.current;
      if (plan) setPlanTodosOverlay(null);
      else if (palette) setCommandPaletteOpen(false);
    },
    { isActive: planTodosOverlay !== null || commandPaletteOpen }
  );

  const commitStreamToScrollback = useCallback(() => {
    if (streamingRef.current) {
      const lines = streamingRef.current.split("\n");
      const newItems: ScrollbackItem[] = [];
      let isFirst = true;
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

  handleMsgRef.current = (msg: BridgeMessage) => {
    switch (msg.type) {
      case "ready":
        setBridgeReady(true);
        setError(null);
        break;
      case "boot_complete":
        setBootInfo({ agentId: msg.agentId, sessionId: msg.sessionId });
        sessionRef.current = `${msg.agentId}/${msg.sessionId}`;
        setLastTuiAbortableStatus(false);
        setTuiActiveDepth(0);
        setUserSendPending(false);
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
          const ri = s.length - 1 - idx;
          const next = [...s];
          next[ri] = { type: "subagent", agent: msg.agent, status: "done", success: msg.success };
          return next;
        });
        break;
      case "status_update": {
        const tab = msg.tui_abortable === true;
        if (msg.tui_abortable !== undefined) {
          setLastTuiAbortableStatus(tab);
        }
        if (tab) {
          if (msg.status === "running") {
            setTuiActiveDepth((d) => d + 1);
            setUserSendPending(false);
          } else if (msg.status === "done") {
            const terminal = ["Done", "Aborted", "Failed"].includes(msg.label);
            if (terminal) {
              setTuiActiveDepth(0);
              setUserSendPending(false);
            } else {
              setTuiActiveDepth((d) => Math.max(0, d - 1));
            }
          }
        }
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
      case "inbound_turn":
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
          return [
            ...s,
            ...prefix,
            {
              type: "inbound_turn_header" as const,
              sourceType: msg.source_type,
              sourceId: msg.source_id,
              prompt: msg.prompt,
            },
            { type: "spacing" as const },
          ];
        });
        break;
      default:
        break;
    }
  };

  // --- SSE connection to gateway (with auto-reconnect) ---
  const connectSse = useCallback((session: string, controller: AbortController) => {
    let retryDelay = 1000;
    const MAX_RETRY = 15000;

    const connect = async () => {
      try {
        const res = await fetch(`${GATEWAY}/v1/sessions/${session}/stream`, {
          signal: controller.signal,
          headers: { Accept: "text/event-stream" },
        });
        if (!res.ok || !res.body) {
          setError(`Gateway error: ${res.status}`);
          return;
        }
        retryDelay = 1000;
        const reader = res.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          bufferRef.current += decoder.decode(value, { stream: true });
          const lines = bufferRef.current.split("\n");
          bufferRef.current = lines.pop() ?? "";
          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed) continue;
            // SSE comment (keepalive) — ignore
            if (trimmed.startsWith(":")) continue;
            if (!trimmed.startsWith("data: ")) continue;
            const payload = trimmed.slice(6);
            const parsed = parseBridgeMessage(payload);
            if (parsed) handleMsgRef.current(parsed);
          }
        }

        // Stream ended cleanly — reconnect unless aborted
        if (!controller.signal.aborted) {
          bufferRef.current = "";
          setTimeout(connect, retryDelay);
          retryDelay = Math.min(retryDelay * 2, MAX_RETRY);
        }
      } catch (err: any) {
        if (err.name === "AbortError") return;
        setError(null); // clear stale error while reconnecting
        setBridgeReady(false);
        if (!controller.signal.aborted) {
          bufferRef.current = "";
          setTimeout(connect, retryDelay);
          retryDelay = Math.min(retryDelay * 2, MAX_RETRY);
        }
      }
    };

    connect();
  }, []);

  const startAgentSwitch = useCallback(async (isInitialPick = false) => {
    agentModeRef.current = true;
    initialAgentPickRef.current = isInitialPick;
    if (isInitialPick) {
      setBootHint("Loading agents...");
    }
    try {
      const res = await fetch(`${GATEWAY}/v1/agents`);
      if (!res.ok) {
        setScrollback((s) => [
          ...s,
          { type: "agent_line", content: `Agent fetch failed: ${res.status}`, isFirst: true, isSystem: true },
        ]);
        if (isInitialPick) {
          setBootHint("Could not load agents. Is the gateway running? Try again after fixing the connection.");
        }
        agentModeRef.current = false;
        initialAgentPickRef.current = false;
        return;
      }
      const data = (await res.json()) as { agents?: { agent_id: string; default_session: string }[] };
      const agents = data.agents ?? [];
      if (agents.length === 0) {
        setScrollback((s) => [
          ...s,
          { type: "agent_line", content: "No agents configured in gateway.yml.", isFirst: true, isSystem: true },
        ]);
        if (isInitialPick) {
          setBootHint("No agents found. Add agents to gateway.yml, then restart.");
        }
        agentModeRef.current = false;
        initialAgentPickRef.current = false;
        return;
      }
      const cancelLabel = "[Cancel]";
      const options = agents.map((a) => {
        const cur = bootInfoRef.current;
        const isCurrent = cur !== null && a.agent_id === cur.agentId;
        return `${a.agent_id}${isCurrent ? " (current)" : ""}`;
      });
      if (!isInitialPick) {
        options.push(cancelLabel);
      }
      setHitlSpec({
        type: "user_input_required" as const,
        method: "select" as const,
        prompt: isInitialPick
          ? "Select an agent workspace to begin:"
          : "Switch agent — select an agent workspace:",
        options,
      });
      if (isInitialPick) {
        setBootHint("Choose an agent below.");
      }
    } catch (err: any) {
      setScrollback((s) => [
        ...s,
        { type: "agent_line", content: `Agent switch error: ${err.message}`, isFirst: true, isSystem: true },
      ]);
      if (isInitialPick) {
        setBootHint(`Could not reach gateway: ${err.message ?? err}`);
      }
      agentModeRef.current = false;
      initialAgentPickRef.current = false;
    }
  }, []);

  useEffect(() => {
    const envSession = process.env.PROXI_SESSION_ID?.trim();
    const ac = new AbortController();
    abortRef.current = ac;

    if (envSession) {
      sessionRef.current = envSession;
      setBootHint("Connecting to gateway...");
      connectSse(envSession, ac);
    } else {
      sessionRef.current = "";
      void startAgentSwitch(true);
    }
    return () => {
      ac.abort();
    };
  }, [connectSse, startAgentSwitch]);

  // --- HTTP helpers ---
  const sendToGateway = useCallback(async (body: Record<string, unknown>) => {
    try {
      const res = await fetch(`${GATEWAY}/v1/sessions/${sessionRef.current}/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const detail = await res.text();
        setError(`Send failed (${res.status}): ${detail || "unknown error"}`);
        setUserSendPending(false);
      }
    } catch (err: any) {
      setError(`Send failed: ${err.message}`);
      setUserSendPending(false);
    }
  }, []);

  const commitStreaming = useCallback(() => {
    commitStreamToScrollback();
  }, [commitStreamToScrollback]);

  // --- MCP management state ---
  const mcpModeRef = useRef(false);

  const startMcpManagement = useCallback(async () => {
    mcpModeRef.current = true;
    const showMcpList = async () => {
      try {
        const res = await fetch(`${GATEWAY}/v1/mcps`);
        if (!res.ok) {
          setScrollback((s) => [
          ...s,
          { type: "agent_line", content: `MCP fetch failed: ${res.status}`, isFirst: true, isSystem: true },
        ]);
          mcpModeRef.current = false;
          return;
        }
        const data = (await res.json()) as { mcps?: { name: string; enabled: boolean }[] };
        const mcps = data.mcps ?? [];
        const doneLabel = "[Done]";
        const options = mcps.map(
          (m) => `${m.name} [${m.enabled ? "Enabled" : "Disabled"}] → ${m.enabled ? "Disable" : "Enable"}`
        );
        options.push(doneLabel);
        setHitlSpec({
          type: "user_input_required" as const,
          method: "select" as const,
          prompt: "MCP Settings: choose an MCP to toggle, or select [Done]",
          options,
        });
      } catch (err: any) {
        setScrollback((s) => [
          ...s,
          { type: "agent_line", content: `MCP error: ${err.message}`, isFirst: true, isSystem: true },
        ]);
        mcpModeRef.current = false;
      }
    };
    await showMcpList();
  }, []);

  const handleMcpSelection = useCallback(async (value: string | boolean | number) => {
    const choice = String(value);
    if (choice === "[Done]" || choice === "false") {
      mcpModeRef.current = false;
      setHitlSpec(null);
      setScrollback((s) => [
        ...s,
        { type: "agent_line", content: "MCP settings updated.", isFirst: true, isSystem: true },
      ]);
      return;
    }
    // Extract MCP name from option string: "name [Enabled] → Disable"
    const mcpName = choice.split(" ")[0];
    if (!mcpName) {
      mcpModeRef.current = false;
      setHitlSpec(null);
      return;
    }
    try {
      const res = await fetch(`${GATEWAY}/v1/mcps/${encodeURIComponent(mcpName)}/toggle`, { method: "POST" });
      if (res.ok) {
        const result = (await res.json()) as { enabled?: boolean };
        setScrollback((s) => [
          ...s,
          {
            type: "agent_line",
            content: `MCP '${mcpName}' ${result.enabled ? "enabled" : "disabled"}.`,
            isFirst: true,
            isSystem: true,
          },
        ]);
      }
    } catch (err: any) {
      setScrollback((s) => [
        ...s,
        { type: "agent_line", content: `Toggle failed: ${err.message}`, isFirst: true, isSystem: true },
      ]);
    }
    // Re-show the list only if the user is still in MCP settings. If they hit [Done] or Esc
    // while the toggle request was in flight, mcpModeRef is false — do not reopen the picker
    // (would steal focus from chat and strand in-flight replies).
    if (mcpModeRef.current) {
      await startMcpManagement();
    }
  }, [startMcpManagement]);

  const handleAgentSelection = useCallback(async (value: string | boolean | number) => {
    const choice = String(value);
    agentModeRef.current = false;
    initialAgentPickRef.current = false;
    setHitlSpec(null);

    if (choice === "[Cancel]" || choice === "false") return;

    const agentId = choice.replace(/ \(current\)$/, "");
    if (bootInfo && agentId === bootInfo.agentId) {
      setScrollback((s) => [
        ...s,
        { type: "agent_line", content: `Already using agent '${agentId}'.`, isFirst: true, isSystem: true },
      ]);
      return;
    }

    setBootHint("Connecting to gateway...");

    try {
      const res = await fetch(`${GATEWAY}/v1/sessions/switch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent_id: agentId }),
      });
      if (!res.ok) {
        const detail = await res.text();
        setScrollback((s) => [
          ...s,
          {
            type: "agent_line",
            content: `Agent switch failed: ${detail || res.statusText}`,
            isFirst: true,
            isSystem: true,
          },
        ]);
        return;
      }
      const result = (await res.json()) as { session_id: string; agent_id: string };

      // Abort existing SSE connection and reconnect to the new session
      if (abortRef.current) abortRef.current.abort();

      sessionRef.current = result.session_id;
      setBootInfo(null);
      setBridgeReady(false);
      setStreamingContent("");
      streamingRef.current = "";
      bufferRef.current = "";
      setUserSendPending(false);
      setTuiActiveDepth(0);
      setLastTuiAbortableStatus(false);

      const ac = new AbortController();
      abortRef.current = ac;
      connectSse(result.session_id, ac);
    } catch (err: any) {
      setScrollback((s) => [
        ...s,
        {
          type: "agent_line",
          content: `Agent switch failed: ${err.message ?? String(err)}`,
          isFirst: true,
          isSystem: true,
        },
      ]);
    }
  }, [bootInfo, connectSse]);

  const onSwitchAgent = useCallback(() => {
    startAgentSwitch();
  }, [startAgentSwitch]);

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
    setUserSendPending(true);
    sendToGateway({ message: task });
  }, [commitStreamToScrollback, sendToGateway]);

  const onHitlSubmit = useCallback((value: string | boolean | number) => {
    if (agentModeRef.current) {
      handleAgentSelection(value);
      return;
    }
    if (mcpModeRef.current) {
      handleMcpSelection(value);
      return;
    }
    setUserSendPending(true);
    sendToGateway({ message: "", form_answer: { value } });
    setHitlSpec(null);
  }, [sendToGateway, handleMcpSelection, handleAgentSelection]);

  const onHitlCancel = useCallback(() => {
    if (agentModeRef.current) {
      if (initialAgentPickRef.current) {
        initialAgentPickRef.current = false;
        agentModeRef.current = false;
        setHitlSpec(null);
        process.exit(0);
        return;
      }
      agentModeRef.current = false;
      initialAgentPickRef.current = false;
      setHitlSpec(null);
      return;
    }
    if (mcpModeRef.current) {
      mcpModeRef.current = false;
      setHitlSpec(null);
      return;
    }
    sendToGateway({ message: "", form_answer: { value: false } });
    setHitlSpec(null);
  }, [sendToGateway]);

  const onAnswerFormSubmit = useCallback(
    (result: { tool_call_id: string; answers: Record<string, unknown>; skipped: boolean }) => {
      setUserSendPending(true);
      sendToGateway({ message: "", form_answer: result });
      setHitlSpec(null);
    },
    [sendToGateway]
  );

  const onAbort = useCallback(async () => {
    commitStreamToScrollback();
    try {
      await fetch(`${GATEWAY}/v1/sessions/${sessionRef.current}/abort`, {
        method: "POST",
      });
    } catch {
      // Best-effort
    }
  }, [commitStreamToScrollback]);
  onAbortRef.current = onAbort;

  useInput(
    (_, key) => {
      if (!key.escape) return;
      if (
        !bootInfo ||
        hitlSpec !== null ||
        planTodosOverlay !== null ||
        commandPaletteOpen ||
        tuiActiveDepth <= 0
      ) {
        return;
      }
      void onAbortRef.current();
    },
    {
      isActive: Boolean(
        bootInfo &&
          hitlSpec === null &&
          planTodosOverlay === null &&
          !commandPaletteOpen &&
          tuiActiveDepth > 0
      ),
    }
  );

  const onCommand = useCallback(
    (cmdId: string) => {
      switch (cmdId) {
        case "agent":
          onSwitchAgent();
          break;
        case "mcps":
          startMcpManagement();
          break;
        case "clear":
          setScrollback([]);
          setStreamingContent("");
          streamingRef.current = "";
          bufferRef.current = "";
          setHitlSpec(null);
          agentModeRef.current = false;
          mcpModeRef.current = false;
          setStatusLabel(null);
          setStatusKind(null);
          setIsProgress(false);
          setUserSendPending(false);
          setTuiActiveDepth(0);
          setLastTuiAbortableStatus(false);
          setError(null);
          void fetch(
            `${GATEWAY}/v1/sessions/${encodeURIComponent(sessionRef.current)}/clear-history`,
            { method: "POST" }
          ).catch(() => {});
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
            { type: "agent_line", content: "/agent - Switch agent workspace", isFirst: true, isSystem: true },
            { type: "agent_line", content: "/mcps  - Enable/disable MCPs", isFirst: false, isSystem: true },
            { type: "agent_line", content: "/clear - Clear UI + session history.jsonl", isFirst: false, isSystem: true },
            { type: "agent_line", content: "/plan  - View current plan", isFirst: false, isSystem: true },
            { type: "agent_line", content: "/todos - View open todos", isFirst: false, isSystem: true },
            { type: "agent_line", content: "/help  - Show all commands", isFirst: false, isSystem: true },
            { type: "agent_line", content: "/exit  - Exit Proxi", isFirst: false, isSystem: true },
          ]);
          break;
        case "exit":
          process.exit(0);
          break;
      }
    },
    [onSwitchAgent, startMcpManagement]
  );

  const minHeight = Math.max(8, (stdout?.rows ?? 24) - 4);

  const showStatusSpinner =
    userSendPending ||
    tuiActiveDepth > 0 ||
    (isProgress && lastTuiAbortableStatus);

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
          showSpinner={showStatusSpinner}
          showAbortHint={tuiActiveDepth > 0 && !hitlSpec}
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
        ) : !bootInfo ? (
          <Box paddingX={1} flexShrink={0}>
            <Text dimColor>{bootHint}</Text>
          </Box>
        ) : commandPaletteOpen ? (
          <CommandPalette
            onDismiss={() => setCommandPaletteOpen(false)}
            onCommand={onCommand}
          />
        ) : planTodosOverlay ? (
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
            disabled={!bridgeReady}
            bridgeReady={bridgeReady}
            onSwitchAgent={onSwitchAgent}
            onOpenCommandPalette={() => setCommandPaletteOpen(true)}
            inputHistory={inputHistory}
          />
        )}
      </Box>
    </Box>
  );
}
