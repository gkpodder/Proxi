/**
 * Minimal TUI for proxi bridge (Step 2).
 * - Spawns bridge with: uv run proxi-bridge from project root.
 * - Shows "Bridge: Ready" when we receive {"type":"ready"}.
 * - Single input; on Enter sends {"type":"start", "task": "..."} and shows response.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Box, Text, useStdout } from "ink";
import { spawn, ChildProcess } from "node:child_process";
import path from "node:path";
import TextInput from "ink-text-input";
import { parseBridgeMessage, type BridgeMessage } from "./protocol.js";

function serializeStart(task: string): string {
  return JSON.stringify({ type: "start", task }) + "\n";
}

export default function App() {
  const { stdout } = useStdout();
  const [bridgeReady, setBridgeReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [agentStatus, setAgentStatus] = useState<string | null>(null);
  const [inputValue, setInputValue] = useState("");
  const [messages, setMessages] = useState<{ role: string; content: string }[]>([]);
  const [streaming, setStreaming] = useState("");

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

    // Use shell so stdin is forwarded to uv's child (the bridge)
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
      case "text_stream":
        streamingRef.current += msg.content;
        setStreaming(streamingRef.current);
        break;
      case "status_update":
        setAgentStatus(msg.label && msg.status === "running" ? msg.label : null);
        if (streamingRef.current) {
          setMessages((m) => [...m, { role: "assistant", content: streamingRef.current }]);
          setStreaming("");
          streamingRef.current = "";
        }
        break;
      default:
        break;
    }
  }

  const onSubmit = useCallback(() => {
    const task = inputValue.trim();
    if (!task) return;
    setMessages((m) => [...m, { role: "user", content: task }]);
    setInputValue("");
    setStreaming("");
    streamingRef.current = "";
    const proc = childRef.current;
    if (proc?.stdin?.writable) {
      proc.stdin.write(serializeStart(task));
    }
  }, [inputValue]);

  return (
    <Box flexDirection="column" paddingX={1}>
      <Box marginBottom={1}>
        <Text color="cyan">
          Bridge: {bridgeReady ? "Ready" : "Starting..."}
          {agentStatus ? `  |  ${agentStatus}` : ""}
        </Text>
      </Box>
      {error && (
        <Box marginBottom={1}>
          <Text color="red">{error}</Text>
        </Box>
      )}
      <Box flexDirection="column" marginBottom={1} minHeight={4}>
        {messages.map((msg, i) => (
          <Box key={i}>
            <Text color={msg.role === "user" ? "cyan" : "green"}>
              {msg.role === "user" ? "> " : "  "}
              {msg.content}
            </Text>
          </Box>
        ))}
        {streaming && (
          <Box>
            <Text color="green">  {streaming}</Text>
          </Box>
        )}
      </Box>
      <Box>
        <Text color="cyan">&gt; </Text>
        {bridgeReady ? (
          <TextInput
            value={inputValue}
            onChange={setInputValue}
            onSubmit={onSubmit}
            placeholder="Type a task and press Enter..."
            showCursor
          />
        ) : (
          <Text dimColor>Waiting for bridge...</Text>
        )}
      </Box>
    </Box>
  );
}
