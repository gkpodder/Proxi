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
  isAskUserQuestionRequired,
} from "./protocol.js";
import type { ScrollbackItem } from "./types/scrollback.js";
import { ScrollbackArea } from "./components/ScrollbackArea.js";
import { InputArea } from "./components/InputArea.js";
import { StatusBar } from "./components/StatusBar.js";
import { HitlForm } from "./components/HitlForm.js";
import { AnswerForm } from "./components/AnswerForm.js";
import { CommandPalette } from "./components/CommandPalette.js";
import { PlanTodosOverlay } from "./components/PlanTodosOverlay.js";
import { PlanModeOverlay } from "./components/PlanModeOverlay.js";
import { UsageOverlay } from "./components/UsageOverlay.js";

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
  const [planTodosOverlay, setPlanTodosOverlay] = useState<"todos" | null>(null);
  const [usageOverlay, setUsageOverlay] = useState<{
    tokens_used: number;
    token_budget: number;
    context_window: number;
    turns_used: number;
    max_turns: number;
  } | null>(null);
  const [inputHistory, setInputHistory] = useState<string[]>([]);
  const [bootHint, setBootHint] = useState("Connecting to gateway...");
  const [userSendPending, setUserSendPending] = useState(false);
  const [tuiActiveDepth, setTuiActiveDepth] = useState(0);
  const [lastTuiAbortableStatus, setLastTuiAbortableStatus] = useState(false);
  const [autoCompactPercent, setAutoCompactPercent] = useState<number | null>(null);
  const [isCompacting, setIsCompacting] = useState(false);
  const [btwMode, setBtwMode] = useState(false);
  const btwReturnSessionRef = useRef<string>("");
  const btwSavedScrollbackRef = useRef<ScrollbackItem[]>([]);
  const [planModeOverlay, setPlanModeOverlay] = useState<string | null>(null);
  const [planModeOverlayMeta, setPlanModeOverlayMeta] = useState<{
    plan_path?: string;
    active_plan_path?: string;
  } | null>(null);
  const planGoalInputRef = useRef(false);
  const [isPlanActive, setIsPlanActive] = useState(false);

  const reasoningEffortModeRef = useRef(false);
  const providerModeRef = useRef(false);
  const [tuiReasoningEffort, setTuiReasoningEffort] = useState<string>("low");
  const [tuiLlmProvider, setTuiLlmProvider] = useState<string | null>(null);

  const bootInfoRef = useRef<{ agentId: string; sessionId: string } | null>(null);
  bootInfoRef.current = bootInfo;

  const abortRef = useRef<AbortController | null>(null);
  const agentModeRef = useRef(false);
  const initialAgentPickRef = useRef(false);
  const createAgentFlowRef = useRef<
    | null
    | {
        step: "name" | "persona";
        draft: Partial<{ name: string; persona: string }>;
      }
  >(null);
  const bufferRef = useRef("");
  const streamingRef = useRef("");
  const overlayRef = useRef({
    planTodosOverlay,
    commandPaletteOpen,
    usageOverlayOpen: usageOverlay !== null,
  });
  overlayRef.current = {
    planTodosOverlay,
    commandPaletteOpen,
    usageOverlayOpen: usageOverlay !== null,
  };

  // Resolved session_id (set from boot_complete)
  const sessionRef = useRef<string>("");
  /** In-flight POST /clear-history; sendToGateway awaits this to avoid racing the server. */
  const clearSessionPromiseRef = useRef<Promise<void> | null>(null);
  const handleMsgRef = useRef<(msg: BridgeMessage) => void>(() => {});
  const onAbortRef = useRef<() => void>(() => {});
  const statsFetchInFlightRef = useRef(false);

  useInput(
    (_, key) => {
      if (!key.escape) return;
      // Order must match render priority: CommandPalette → UsageOverlay → PlanTodosOverlay
      const { planTodosOverlay: plan, commandPaletteOpen: palette, usageOverlayOpen } = overlayRef.current;
      if (palette) setCommandPaletteOpen(false);
      else if (usageOverlayOpen) setUsageOverlay(null);
      else if (plan) setPlanTodosOverlay(null);
    },
    { isActive: planTodosOverlay !== null || commandPaletteOpen || usageOverlay !== null }
  );

  useInput(
    (_, key) => {
      if (!key.escape) return;
      handleBtwReturn();
    },
    {
      isActive:
        btwMode &&
        hitlSpec === null &&
        !commandPaletteOpen &&
        usageOverlay === null &&
        planTodosOverlay === null,
    }
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
    // Only show events from the TUI's own prompts or from broadcast sources (cron/heartbeat/webhook).
    // Events from other interactive channels (discord, react) are filtered out.
    // source_id identifies the named source; source_type identifies its kind.
    const msgSourceId = (msg as { source_id?: string }).source_id;
    const msgSourceType = (msg as { source_type?: string }).source_type;
    if (msgSourceId || msgSourceType) {
      const BROADCAST_TYPES = new Set(["cron", "heartbeat", "webhook"]);
      const isTui = msgSourceId === "tui";
      const isBroadcast = BROADCAST_TYPES.has(msgSourceType ?? "") || BROADCAST_TYPES.has(msgSourceId ?? "");
      if (!isTui && !isBroadcast) {
        const DISPLAY_TYPES = new Set([
          "text_stream", "tool_start", "tool_log", "tool_done",
          "subagent_start", "subagent_done", "inbound_turn", "status_update",
        ]);
        if (DISPLAY_TYPES.has(msg.type)) return;
      }
    }
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
        setIsCompacting(false);
        void refreshSessionStats();
        void refreshLlmConfig();
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
        const statusLabelLower = (msg.label ?? "").toLowerCase();
        const isCompactionStatus = statusLabelLower.includes("compact");
        if (isCompactionStatus) {
          setIsCompacting(msg.status === "running");
        }
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
        if (msg.status === "done") {
          void refreshSessionStats();
        }
        commitStreamToScrollback();
        break;
      }
      case "user_input_required":
        setHitlSpec(msg);
        break;
      case "plan_ready":
        commitStreamToScrollback();
        setPlanModeOverlay(msg.content);
        setPlanModeOverlayMeta({
          plan_path: (msg as import("./protocol.js").PlanReady).plan_path,
          active_plan_path: (msg as import("./protocol.js").PlanReady).active_plan_path,
        });
        setIsPlanActive(true);
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
        const res = await fetch(`${GATEWAY}/v1/sessions/${session}/stream?subscriber=tui`, {
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
        createAgentFlowRef.current = { step: "name", draft: {} };
        setHitlSpec({
          type: "user_input_required" as const,
          method: "text" as const,
          prompt: isInitialPick
            ? "No agents yet — create one. Display name:"
            : "Create new agent — display name:",
        });
        if (isInitialPick) {
          setBootHint("Type a name for your first agent.");
        }
        agentModeRef.current = false;
        return;
      }
      const cancelLabel = "[Cancel]";
      const options = agents.map((a) => {
        const cur = bootInfoRef.current;
        const isCurrent = cur !== null && a.agent_id === cur.agentId;
        return `${a.agent_id}${isCurrent ? " (current)" : ""}`;
      });
      options.push("[+] Create new agent");
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

  const performDeleteAgent = useCallback(async () => {
    const agentId = bootInfoRef.current?.agentId;
    if (!agentId) return;
    setBootHint("Deleting agent...");
    try {
      const res = await fetch(`${GATEWAY}/v1/agents/${encodeURIComponent(agentId)}`, {
        method: "DELETE",
      });
      if (!res.ok) {
        const detail = await res.text();
        setScrollback((s) => [
          ...s,
          {
            type: "agent_line",
            content: `Delete failed: ${detail || res.status}`,
            isFirst: true,
            isSystem: true,
          },
        ]);
        setBootHint("");
        return;
      }
      setScrollback((s) => [
        ...s,
        {
          type: "agent_line",
          content: `Agent '${agentId}' deleted.`,
          isFirst: true,
          isSystem: true,
        },
      ]);
      if (abortRef.current) abortRef.current.abort();
      setBootInfo(null);
      setBridgeReady(false);
      setStreamingContent("");
      streamingRef.current = "";
      bufferRef.current = "";
      setUserSendPending(false);
      setTuiActiveDepth(0);
      setLastTuiAbortableStatus(false);
      setIsCompacting(false);
      setError(null);
      sessionRef.current = "";
      setBootHint("Choose an agent below.");
      void startAgentSwitch(true);
    } catch (err: any) {
      setScrollback((s) => [
        ...s,
        {
          type: "agent_line",
          content: `Delete failed: ${err.message ?? String(err)}`,
          isFirst: true,
          isSystem: true,
        },
      ]);
      setBootHint("");
    }
  }, [startAgentSwitch]);

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
  const refreshSessionStats = useCallback(async () => {
    const sid = sessionRef.current;
    if (!sid || statsFetchInFlightRef.current) return;
    statsFetchInFlightRef.current = true;
    try {
      const res = await fetch(`${GATEWAY}/v1/sessions/${encodeURIComponent(sid)}/stats`);
      if (!res.ok) return;
      const stats = (await res.json()) as {
        tokens_used: number;
        context_window: number;
        compaction_threshold?: number;
      };
      const thresholdFraction = stats.compaction_threshold ?? 0.7;
      const thresholdTokens = Math.max(1, Math.floor(stats.context_window * thresholdFraction));
      const remaining = Math.max(0, thresholdTokens - stats.tokens_used);
      setAutoCompactPercent(Math.round((remaining / thresholdTokens) * 100));
    } catch {
      // best effort
    } finally {
      statsFetchInFlightRef.current = false;
    }
  }, []);

  const sendToGateway = useCallback(async (body: Record<string, unknown>) => {
    const pendingClear = clearSessionPromiseRef.current;
    if (pendingClear) {
      try {
        await pendingClear;
      } catch {
        // clear-history is best-effort; continue with send
      }
    }
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

  const refreshLlmConfig = useCallback(async () => {
    try {
      const res = await fetch(`${GATEWAY}/v1/llm-config`);
      if (!res.ok) return;
      const data = (await res.json()) as { provider?: string };
      if (data.provider) setTuiLlmProvider(data.provider);
    } catch {
      // best effort
    }
  }, []);

  const startProviderFlow = useCallback(async () => {
    providerModeRef.current = true;
    try {
      const res = await fetch(`${GATEWAY}/v1/llm-config`);
      if (!res.ok) {
        providerModeRef.current = false;
        setScrollback((s) => [
          ...s,
          {
            type: "agent_line",
            content: `Could not load LLM config (${res.status}). Is the gateway running?`,
            isFirst: true,
            isSystem: true,
          },
        ]);
        return;
      }
      const data = (await res.json()) as { provider: string; model: string; providers: string[] };
      setTuiLlmProvider(data.provider);
      const title =
        data.provider === "openai"
          ? "OpenAI"
          : data.provider === "anthropic"
            ? "Anthropic"
            : data.provider;
      setHitlSpec({
        type: "user_input_required" as const,
        method: "select" as const,
        prompt: `Gateway LLM\nCurrent: ${title} — ${data.model}\nApplies to every session until you switch again.`,
        options: [...data.providers].sort(),
        ui: "provider",
        preferredOption: data.provider,
      });
    } catch (err: unknown) {
      providerModeRef.current = false;
      const m = err instanceof Error ? err.message : String(err);
      setScrollback((s) => [
        ...s,
        { type: "agent_line", content: `LLM config error: ${m}`, isFirst: true, isSystem: true },
      ]);
    }
  }, []);

  const handleProviderSubmit = useCallback(
    async (value: string | boolean | number) => {
      providerModeRef.current = false;
      setHitlSpec(null);
      const chosen = String(value).trim().toLowerCase();
      if (!chosen) return;
      if (chosen === tuiLlmProvider) {
        setScrollback((s) => [
          ...s,
          {
            type: "agent_line",
            content: `Already using provider '${chosen}'.`,
            isFirst: true,
            isSystem: true,
          },
        ]);
        return;
      }
      try {
        const res = await fetch(`${GATEWAY}/v1/llm-config`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ provider: chosen, model: "" }),
        });
        const raw = await res.text();
        if (res.ok) {
          try {
            const data = JSON.parse(raw) as { provider: string; model: string };
            setTuiLlmProvider(data.provider);
            setScrollback((s) => [
              ...s,
              {
                type: "agent_line",
                content: `LLM → ${data.provider} · ${data.model}`,
                isFirst: true,
                isSystem: true,
              },
            ]);
          } catch {
            setTuiLlmProvider(chosen);
            setScrollback((s) => [
              ...s,
              {
                type: "agent_line",
                content: `LLM provider updated to ${chosen}.`,
                isFirst: true,
                isSystem: true,
              },
            ]);
          }
          return;
        }
        let errDetail = raw || res.statusText;
        try {
          const j = JSON.parse(raw) as { detail?: string };
          if (j.detail) errDetail = String(j.detail);
        } catch {
          /* keep text */
        }
        setScrollback((s) => [
          ...s,
          {
            type: "agent_line",
            content: `Provider switch failed: ${errDetail}`,
            isFirst: true,
            isSystem: true,
          },
        ]);
      } catch (err: unknown) {
        const m = err instanceof Error ? err.message : String(err);
        setScrollback((s) => [
          ...s,
          {
            type: "agent_line",
            content: `Provider switch failed: ${m}`,
            isFirst: true,
            isSystem: true,
          },
        ]);
      }
    },
    [tuiLlmProvider]
  );

  const commitStreaming = useCallback(() => {
    commitStreamToScrollback();
  }, [commitStreamToScrollback]);

  // --- Integration management state ---
  const integrationModeRef = useRef(false);
  const deleteModeRef = useRef(false);
  const workDirModeRef = useRef(false);
  const compactModeRef = useRef(false);

  const startIntegrationManagement = useCallback(async () => {
    integrationModeRef.current = true;
    const showIntegrationList = async () => {
      try {
        const res = await fetch(`${GATEWAY}/v1/integrations`);
        if (!res.ok) {
          setScrollback((s) => [
          ...s,
          { type: "agent_line", content: `Integration fetch failed: ${res.status}`, isFirst: true, isSystem: true },
        ]);
          integrationModeRef.current = false;
          return;
        }
        const data = (await res.json()) as { integrations?: { name: string; enabled: boolean }[] };
        const integrations = data.integrations ?? [];
        const doneLabel = "[Done]";
        const options = integrations.map(
          (m) => `${m.name} [${m.enabled ? "Enabled" : "Disabled"}] → ${m.enabled ? "Disable" : "Enable"}`
        );
        options.push(doneLabel);
        setHitlSpec({
          type: "user_input_required" as const,
          method: "select" as const,
          prompt: "Integration Settings: choose an integration to toggle, or select [Done]",
          options,
        });
      } catch (err: any) {
        setScrollback((s) => [
          ...s,
          { type: "agent_line", content: `Integration error: ${err.message}`, isFirst: true, isSystem: true },
        ]);
        integrationModeRef.current = false;
      }
    };
    await showIntegrationList();
  }, []);

  const handleIntegrationSelection = useCallback(async (value: string | boolean | number) => {
    const choice = String(value);
    if (choice === "[Done]" || choice === "false") {
      integrationModeRef.current = false;
      setHitlSpec(null);
      setScrollback((s) => [
        ...s,
        { type: "agent_line", content: "Integration settings updated.", isFirst: true, isSystem: true },
      ]);
      return;
    }
    // Extract integration name from option string: "name [Enabled] → Disable"
    const integrationName = choice.split(" ")[0];
    if (!integrationName) {
      integrationModeRef.current = false;
      setHitlSpec(null);
      return;
    }
    try {
      const res = await fetch(`${GATEWAY}/v1/integrations/${encodeURIComponent(integrationName)}/toggle`, { method: "POST" });
      if (res.ok) {
        const result = (await res.json()) as { enabled?: boolean };
        setScrollback((s) => [
          ...s,
          {
            type: "agent_line",
            content: `Integration '${integrationName}' ${result.enabled ? "enabled" : "disabled"}.`,
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
    // Re-show the list only if the user is still in integration settings. If they hit [Done] or Esc
    // while the toggle request was in flight, integrationModeRef is false — do not reopen the picker
    // (would steal focus from chat and strand in-flight replies).
    if (integrationModeRef.current) {
      await startIntegrationManagement();
    }
  }, [startIntegrationManagement]);

  const startWorkDirFlow = useCallback(async () => {
    workDirModeRef.current = true;
    try {
      const agentId = bootInfoRef.current?.agentId;
      const qs = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : "";
      const res = await fetch(`${GATEWAY}/v1/working-dir${qs}`);
      const data = res.ok ? (await res.json() as { path?: string }) : { path: "unknown" };
      const current = data.path ?? "unknown";
      setHitlSpec({
        type: "user_input_required" as const,
        method: "text" as const,
        prompt: `Working dir: ${current}\nEnter new path (leave empty to cancel):`,
      });
    } catch {
      workDirModeRef.current = false;
      setScrollback((s) => [
        ...s,
        { type: "agent_line", content: "Could not reach gateway.", isFirst: true, isSystem: true },
      ]);
    }
  }, []);

  const handlePlanGoalSubmit = useCallback((value: string | boolean | number) => {
    planGoalInputRef.current = false;
    setHitlSpec(null);
    const goal = String(value).trim();
    if (!goal) {
      setIsPlanActive(false);
      return;
    }
    setIsPlanActive(true);
    const msg = `/plan ${goal}`;
    setScrollback((s) => [...s, { type: "user", content: msg }, { type: "spacing" as const }]);
    setUserSendPending(true);
    void sendToGateway({ message: msg });
  }, [sendToGateway]);

  const handlePlanAccept = useCallback(async () => {
    const sid = sessionRef.current;
    setIsPlanActive(false);
    setPlanModeOverlay(null);
    setPlanModeOverlayMeta(null);
    try {
      await fetch(`${GATEWAY}/v1/sessions/${encodeURIComponent(sid)}/plan/accept`, { method: "POST" });
    } catch {
      setScrollback((s) => [
        ...s,
        { type: "agent_line", content: "Could not accept plan — gateway unreachable.", isFirst: true, isSystem: true },
      ]);
    }
  }, []);

  const handlePlanRefine = useCallback((feedback: string) => {
    setPlanModeOverlay(null);
    setPlanModeOverlayMeta(null);
    // Keep plan mode active while the new plan is being generated.
    const msg = `/plan refine ${feedback}`;
    setScrollback((s) => [...s, { type: "user", content: msg }, { type: "spacing" as const }]);
    setUserSendPending(true);
    void sendToGateway({ message: msg });
  }, [sendToGateway]);

  const handlePlanReject = useCallback(async () => {
    const sid = sessionRef.current;
    setIsPlanActive(false);
    setPlanModeOverlay(null);
    setPlanModeOverlayMeta(null);
    try {
      await fetch(`${GATEWAY}/v1/sessions/${encodeURIComponent(sid)}/plan/reject`, { method: "POST" });
    } catch {
      setScrollback((s) => [
        ...s,
        { type: "agent_line", content: "Could not reject plan — gateway unreachable.", isFirst: true, isSystem: true },
      ]);
    }
  }, []);

  const handleCompactSubmit = useCallback((value: string | boolean | number) => {
    compactModeRef.current = false;
    setHitlSpec(null);
    const focus = String(value).trim();
    const msg = focus ? `/compact ${focus}` : "/compact";
    setScrollback((s) => [...s, { type: "user", content: msg }, { type: "spacing" as const }]);
    void sendToGateway({ message: msg });
  }, [sendToGateway]);

  const handleReasoningEffortSubmit = useCallback((value: string | boolean | number) => {
    reasoningEffortModeRef.current = false;
    setHitlSpec(null);
    const level = String(value).trim().toLowerCase() || "minimal";
    const valid = ["minimal", "low", "medium", "high"];
    const resolved = valid.includes(level) ? level : "minimal";
    setTuiReasoningEffort(resolved);
    void sendToGateway({ message: `/reasoning-effort ${resolved}` });
  }, [sendToGateway]);

  const handleWorkDirSubmit = useCallback(async (value: string | boolean | number) => {
    workDirModeRef.current = false;
    setHitlSpec(null);
    const newPath = String(value).trim();
    if (!newPath) return;
    try {
      const agentId = bootInfoRef.current?.agentId;
      const res = await fetch(`${GATEWAY}/v1/working-dir`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: newPath, agent_id: agentId ?? null }),
      });
      const data = (await res.json()) as { path?: string; detail?: string };
      if (res.ok) {
        setScrollback((s) => [
          ...s,
          { type: "agent_line", content: `Working dir set to: ${data.path}`, isFirst: true, isSystem: true },
        ]);
      } else {
        setScrollback((s) => [
          ...s,
          { type: "agent_line", content: `Error: ${data.detail ?? "unknown error"}`, isFirst: true, isSystem: true },
        ]);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setScrollback((s) => [
        ...s,
        { type: "agent_line", content: `Error: ${msg}`, isFirst: true, isSystem: true },
      ]);
    }
  }, []);

  const handleCreateAgentFlowSubmit = useCallback(
    async (value: string | boolean | number) => {
      const flow = createAgentFlowRef.current;
      if (!flow) return;
      const v = String(value).trim();
      if (flow.step === "name") {
        if (!v) {
          setScrollback((s) => [
            ...s,
            {
              type: "agent_line",
              content: "Display name cannot be empty.",
              isFirst: true,
              isSystem: true,
            },
          ]);
          return;
        }
        flow.draft.name = v;
        flow.step = "persona";
        setHitlSpec({
          type: "user_input_required" as const,
          method: "text" as const,
          prompt: "Persona:",
        });
        return;
      }
      if (flow.step === "persona") {
        const draft = {
          name: flow.draft.name ?? "",
          persona: v || "Helpful, patient, and clear.",
        };
        createAgentFlowRef.current = null;
        setHitlSpec(null);

        try {
          const res = await fetch(`${GATEWAY}/v1/agents`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              name: draft.name,
              persona: draft.persona,
            }),
          });
          if (!res.ok) {
            const detail = await res.text();
            setScrollback((s) => [
              ...s,
              {
                type: "agent_line",
                content: `Create agent failed: ${detail || res.status}`,
                isFirst: true,
                isSystem: true,
              },
            ]);
            if (initialAgentPickRef.current) {
              setBootHint("Create failed. Check gateway logs or gateway.yml.");
            }
            return;
          }
          const data = (await res.json()) as { agent_id: string };
          setBootHint("Connecting to gateway...");
          if (abortRef.current) abortRef.current.abort();
          const switchRes = await fetch(`${GATEWAY}/v1/sessions/switch`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ agent_id: data.agent_id }),
          });
          if (!switchRes.ok) {
            const detail = await switchRes.text();
            setScrollback((s) => [
              ...s,
              {
                type: "agent_line",
                content: `Switch to new agent failed: ${detail || switchRes.status}`,
                isFirst: true,
                isSystem: true,
              },
            ]);
            return;
          }
          const result = (await switchRes.json()) as { session_id: string; agent_id: string };
          sessionRef.current = result.session_id;
          setBootInfo(null);
          setBridgeReady(false);
          setStreamingContent("");
          streamingRef.current = "";
          bufferRef.current = "";
          setUserSendPending(false);
          setTuiActiveDepth(0);
          setLastTuiAbortableStatus(false);
      setIsCompacting(false);
          initialAgentPickRef.current = false;
          const ac = new AbortController();
          abortRef.current = ac;
          connectSse(result.session_id, ac);
        } catch (err: any) {
          setScrollback((s) => [
            ...s,
            {
              type: "agent_line",
              content: `Create agent failed: ${err.message ?? String(err)}`,
              isFirst: true,
              isSystem: true,
            },
          ]);
        }
      }
    },
    [connectSse]
  );

  const handleAgentSelection = useCallback(async (value: string | boolean | number) => {
    const choice = String(value);
    if (choice === "[+] Create new agent") {
      createAgentFlowRef.current = { step: "name", draft: {} };
      setHitlSpec({
        type: "user_input_required" as const,
        method: "text" as const,
        prompt: "New agent — display name:",
      });
      agentModeRef.current = false;
      return;
    }
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
      setIsCompacting(false);

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

  const handleBranch = useCallback(async () => {
    const currentSession = sessionRef.current;
    if (!currentSession) return;
    setScrollback((s) => [
      ...s,
      { type: "agent_line", content: "Branching agent…", isFirst: true, isSystem: true },
    ]);
    try {
      const res = await fetch(
        `${GATEWAY}/v1/sessions/${encodeURIComponent(currentSession)}/branch`,
        { method: "POST" }
      );
      if (!res.ok) {
        const detail = await res.text();
        setScrollback((s) => [
          ...s,
          { type: "agent_line", content: `Branch failed: ${detail || res.status}`, isFirst: true, isSystem: true },
        ]);
        return;
      }
      const result = (await res.json()) as { agent_id: string; session_id: string };
      setScrollback((s) => [
        ...s,
        { type: "agent_line", content: `Branched → ${result.agent_id}. Switching…`, isFirst: true, isSystem: true },
      ]);
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
      setIsCompacting(false);
      const ac = new AbortController();
      abortRef.current = ac;
      connectSse(result.session_id, ac);
    } catch (err: any) {
      setScrollback((s) => [
        ...s,
        { type: "agent_line", content: `Branch error: ${err.message ?? String(err)}`, isFirst: true, isSystem: true },
      ]);
    }
  }, [connectSse]);

  const handleBtwReturn = useCallback(() => {
    const returnSession = btwReturnSessionRef.current;
    const btwSession = sessionRef.current;
    if (!returnSession || !btwMode) return;
    setBtwMode(false);
    btwReturnSessionRef.current = "";
    const savedScrollback = btwSavedScrollbackRef.current;
    btwSavedScrollbackRef.current = [];
    if (abortRef.current) abortRef.current.abort();
    sessionRef.current = returnSession;
    setBootInfo(null);
    setBridgeReady(false);
    setScrollback(savedScrollback);
    setStreamingContent("");
    streamingRef.current = "";
    bufferRef.current = "";
    setUserSendPending(false);
    setTuiActiveDepth(0);
    setLastTuiAbortableStatus(false);
    setIsCompacting(false);
    const ac = new AbortController();
    abortRef.current = ac;
    connectSse(returnSession, ac);
    // Delete the btw session after reconnecting (fire-and-forget)
    if (btwSession) {
      fetch(`${GATEWAY}/v1/sessions/${encodeURIComponent(btwSession)}`, { method: "DELETE" }).catch(() => undefined);
    }
  }, [btwMode, connectSse]);

  const handleBtw = useCallback(async () => {
    const currentSession = sessionRef.current;
    if (!currentSession) return;
    try {
      const res = await fetch(
        `${GATEWAY}/v1/sessions/${encodeURIComponent(currentSession)}/btw`,
        { method: "POST" }
      );
      if (!res.ok) {
        const detail = await res.text();
        setScrollback((s) => [
          ...s,
          { type: "agent_line", content: `BTW failed: ${detail || res.status}`, isFirst: true, isSystem: true },
        ]);
        return;
      }
      const result = (await res.json()) as { btw_session_id: string; return_session_id: string };
      btwReturnSessionRef.current = result.return_session_id;
      btwSavedScrollbackRef.current = scrollback;
      setBtwMode(true);
      if (abortRef.current) abortRef.current.abort();
      sessionRef.current = result.btw_session_id;
      setBootInfo(null);
      setBridgeReady(false);
      setScrollback([]);
      setStreamingContent("");
      streamingRef.current = "";
      bufferRef.current = "";
      setUserSendPending(false);
      setTuiActiveDepth(0);
      setLastTuiAbortableStatus(false);
      setIsCompacting(false);
      const ac = new AbortController();
      abortRef.current = ac;
      connectSse(result.btw_session_id, ac);
    } catch (err: any) {
      setScrollback((s) => [
        ...s,
        { type: "agent_line", content: `BTW error: ${err.message ?? String(err)}`, isFirst: true, isSystem: true },
      ]);
    }
  }, [connectSse, scrollback]);

  const onSubmit = useCallback((task: string, _provider: string, _maxTurns: number) => {
    if (!task.trim()) return;
    if (task.trim() === "/provider") {
      void startProviderFlow();
      return;
    }
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
  }, [commitStreamToScrollback, sendToGateway, startProviderFlow]);

  const onHitlSubmit = useCallback(
    (value: string | boolean | number) => {
      if (createAgentFlowRef.current) {
        void handleCreateAgentFlowSubmit(value);
        return;
      }
      if (deleteModeRef.current) {
        deleteModeRef.current = false;
        setHitlSpec(null);
        if (value === true) {
          void performDeleteAgent();
        }
        return;
      }
      if (agentModeRef.current) {
        void handleAgentSelection(value);
        return;
      }
      if (integrationModeRef.current) {
        handleIntegrationSelection(value);
        return;
      }
      if (workDirModeRef.current) {
        void handleWorkDirSubmit(value);
        return;
      }
      if (compactModeRef.current) {
        handleCompactSubmit(value);
        return;
      }
      if (planGoalInputRef.current) {
        handlePlanGoalSubmit(value);
        return;
      }
      if (providerModeRef.current) {
        void handleProviderSubmit(value);
        return;
      }
      if (reasoningEffortModeRef.current) {
        handleReasoningEffortSubmit(value);
        return;
      }
      setUserSendPending(true);
      sendToGateway({ message: "", form_answer: { value } });
      setHitlSpec(null);
    },
    [
      sendToGateway,
      handleIntegrationSelection,
      handleAgentSelection,
      handleCreateAgentFlowSubmit,
      performDeleteAgent,
      handleWorkDirSubmit,
      handleCompactSubmit,
      handlePlanGoalSubmit,
      handleProviderSubmit,
      handleReasoningEffortSubmit,
    ]
  );

  const onHitlCancel = useCallback(() => {
    if (createAgentFlowRef.current) {
      createAgentFlowRef.current = null;
      setHitlSpec(null);
      if (initialAgentPickRef.current) {
        process.exit(0);
      }
      return;
    }
    if (deleteModeRef.current) {
      deleteModeRef.current = false;
      setHitlSpec(null);
      return;
    }
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
    if (integrationModeRef.current) {
      integrationModeRef.current = false;
      setHitlSpec(null);
      return;
    }
    if (workDirModeRef.current) {
      workDirModeRef.current = false;
      setHitlSpec(null);
      return;
    }
    if (compactModeRef.current) {
      compactModeRef.current = false;
      setHitlSpec(null);
      return;
    }
    if (planGoalInputRef.current) {
      planGoalInputRef.current = false;
      setHitlSpec(null);
      setIsPlanActive(false);
      return;
    }
    if (reasoningEffortModeRef.current) {
      reasoningEffortModeRef.current = false;
      setHitlSpec(null);
      return;
    }
    if (providerModeRef.current) {
      providerModeRef.current = false;
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
        usageOverlay !== null ||
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
          usageOverlay === null &&
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
        case "branch":
          if (!bootInfo) {
            setScrollback((s) => [
              ...s,
              { type: "agent_line", content: "Connect to an agent first, then use /branch.", isFirst: true, isSystem: true },
            ]);
            break;
          }
          void handleBranch();
          break;
        case "btw":
          if (!bootInfo) {
            setScrollback((s) => [
              ...s,
              { type: "agent_line", content: "Connect to an agent first, then use /btw.", isFirst: true, isSystem: true },
            ]);
            break;
          }
          void handleBtw();
          break;
        case "delete":
          if (!bootInfo) {
            setScrollback((s) => [
              ...s,
              {
                type: "agent_line",
                content: "Connect to an agent first, then use /delete.",
                isFirst: true,
                isSystem: true,
              },
            ]);
            break;
          }
          deleteModeRef.current = true;
          setHitlSpec({
            type: "user_input_required" as const,
            method: "confirm" as const,
            prompt: `Delete agent '${bootInfo.agentId}' and all sessions? This cannot be undone.`,
          });
          break;
        case "integrations":
          startIntegrationManagement();
          break;
        case "work-dir":
          void startWorkDirFlow();
          break;
        case "compact":
          if (!bootInfo) {
            setScrollback((s) => [
              ...s,
              { type: "agent_line", content: "Connect to an agent first, then use /compact.", isFirst: true, isSystem: true },
            ]);
            break;
          }
          compactModeRef.current = true;
          setHitlSpec({
            type: "user_input_required" as const,
            method: "text" as const,
            ui: "compact",
          });
          break;
        case "clear":
          setScrollback([]);
          setStreamingContent("");
          streamingRef.current = "";
          bufferRef.current = "";
          setHitlSpec(null);
          setUsageOverlay(null);
          agentModeRef.current = false;
          integrationModeRef.current = false;
          deleteModeRef.current = false;
          setStatusLabel(null);
          setStatusKind(null);
          setIsProgress(false);
          setUserSendPending(false);
          setTuiActiveDepth(0);
          setLastTuiAbortableStatus(false);
          setIsCompacting(false);
          setError(null);
          {
            const p = fetch(
              `${GATEWAY}/v1/sessions/${encodeURIComponent(sessionRef.current)}/clear-history`,
              { method: "POST" }
            )
              .then(() => undefined)
              .catch(() => undefined)
              .finally(() => {
                if (clearSessionPromiseRef.current === p) {
                  clearSessionPromiseRef.current = null;
                }
              });
            clearSessionPromiseRef.current = p;
          }
          break;
        case "plan":
          if (!bootInfo) {
            setScrollback((s) => [
              ...s,
              { type: "agent_line", content: "Connect to an agent first, then use /plan.", isFirst: true, isSystem: true },
            ]);
            break;
          }
          planGoalInputRef.current = true;
          setIsPlanActive(true);
          setHitlSpec({
            type: "user_input_required" as const,
            method: "text" as const,
            ui: "plan",
          });
          break;
        case "reasoning-effort":
          reasoningEffortModeRef.current = true;
          setHitlSpec({
            type: "user_input_required" as const,
            method: "select" as const,
            prompt: "Reasoning effort",
            options: ["minimal", "low", "medium", "high"],
            ui: "reasoning-effort",
          });
          break;
        case "provider":
          void startProviderFlow();
          break;
        case "todos":
          setPlanTodosOverlay("todos");
          break;
        case "usage": {
          const sid = sessionRef.current;
          if (!sid) {
            setScrollback((s) => [
              ...s,
              { type: "agent_line", content: "No active session.", isFirst: true, isSystem: true },
            ]);
            break;
          }
          fetch(`${GATEWAY}/v1/sessions/${encodeURIComponent(sid)}/stats`)
            .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
            .then((data) => {
              const stats = data as {
                tokens_used: number;
                token_budget: number;
                context_window: number;
                turns_used: number;
                max_turns: number;
              };
              setPlanTodosOverlay(null);
              setUsageOverlay(stats);
            })
            .catch(() => {
              setScrollback((s) => [
                ...s,
                { type: "agent_line", content: "Could not fetch usage stats — start a session first.", isFirst: true, isSystem: true },
              ]);
            });
          break;
        }
        case "help":
          setScrollback((s) => [
            ...s,
            { type: "agent_line", content: "/agent    - Switch agent or create [+] Create new agent", isFirst: true, isSystem: true },
            { type: "agent_line", content: "/branch   - Clone current agent with full session history", isFirst: false, isSystem: true },
            { type: "agent_line", content: "/btw      - Temporary side session (Esc from empty input to return)", isFirst: false, isSystem: true },
            { type: "agent_line", content: "/delete   - Delete current agent (gateway.yml + ~/.proxi/agents)", isFirst: false, isSystem: true },
            { type: "agent_line", content: "/integrations - Enable/disable integrations (gmail, spotify, etc.)", isFirst: false, isSystem: true },
            { type: "agent_line", content: "/work-dir - View or change working directory", isFirst: false, isSystem: true },
            { type: "agent_line", content: "/compact  - Summarize context to save tokens (optionally add a focus hint)", isFirst: false, isSystem: true },
            { type: "agent_line", content: "/clear    - Clear UI + session history.jsonl", isFirst: false, isSystem: true },
            { type: "agent_line", content: "/plan     - Start an interactive planning session", isFirst: false, isSystem: true },
            { type: "agent_line", content: "/provider - Switch LLM provider (OpenAI · Anthropic)", isFirst: false, isSystem: true },
            { type: "agent_line", content: "/todos    - View open todos", isFirst: false, isSystem: true },
            { type: "agent_line", content: "/usage    - Show context and turn usage", isFirst: false, isSystem: true },
            { type: "agent_line", content: "/help     - Show all commands", isFirst: false, isSystem: true },
            { type: "agent_line", content: "/exit     - Exit Proxi", isFirst: false, isSystem: true },
          ]);
          break;
        case "exit":
          process.exit(0);
          break;
      }
    },
    [onSwitchAgent, startIntegrationManagement, startWorkDirFlow, bootInfo, handleBranch, handleBtw, startProviderFlow]
  );

  const minHeight = Math.max(8, (stdout?.rows ?? 24) - 4);

  const showStatusSpinner =
    isCompacting ||
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
          isBtw={btwMode}
          isCompacting={isCompacting}
          isPlanMode={isPlanActive}
          reasoningEffort={tuiReasoningEffort}
          llmProvider={tuiLlmProvider}
          autoCompactPercent={autoCompactPercent}
        />
        {hitlSpec ? (
          isAskUserQuestionRequired(hitlSpec) ? (
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
        ) : usageOverlay ? (
          <UsageOverlay stats={usageOverlay} />
        ) : planModeOverlay ? (
          <PlanModeOverlay
            content={planModeOverlay}
            planPath={planModeOverlayMeta?.plan_path}
            activePlanPath={planModeOverlayMeta?.active_plan_path}
            onAccept={handlePlanAccept}
            onRefine={handlePlanRefine}
            onReject={handlePlanReject}
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
            disabled={!bridgeReady || isCompacting}
            bridgeReady={bridgeReady}
            onSwitchAgent={onSwitchAgent}
            onOpenCommandPalette={() => setCommandPaletteOpen(true)}
            inputHistory={inputHistory}
            onEscapeEmpty={btwMode ? handleBtwReturn : undefined}
            activeProvider={tuiLlmProvider ?? "openai"}
          />
        )}
      </Box>
    </Box>
  );
}
