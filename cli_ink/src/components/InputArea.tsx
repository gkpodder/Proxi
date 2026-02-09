import React, { useState, useCallback, useRef } from "react";
import { Box, Text, useInput } from "ink";
import TextInput from "ink-text-input";

type Props = {
  onSubmit: (task: string, provider: "openai" | "anthropic", maxTurns: number) => void;
  onCommitStreaming: () => void;
  disabled: boolean;
  bridgeReady: boolean;
  inputAllowedOverride?: boolean; // true when we allow input after timeout even if bridge not ready
};

const HISTORY_MAX = 50;

export function InputArea({
  onSubmit,
  onCommitStreaming,
  disabled,
  bridgeReady,
  inputAllowedOverride = false,
}: Props) {
  const [value, setValue] = useState("");
  const [history, setHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const historyRef = useRef<string[]>([]);
  historyRef.current = history;

  const submit = useCallback(() => {
    const task = value.trim();
    if (!task) return;
    onCommitStreaming();
    onSubmit(task, "openai", 50);
    setValue("");
    setHistory((prev) => {
      const next = [task, ...prev.filter((t) => t !== task)].slice(0, HISTORY_MAX);
      historyRef.current = next;
      return next;
    });
    setHistoryIndex(-1);
  }, [value, onSubmit, onCommitStreaming]);

  useInput((input, key) => {
    if (disabled) return;
    if (key.upArrow) {
      if (historyRef.current.length === 0) return;
      setHistoryIndex((i) => {
        const next = i === -1 ? 0 : Math.min(i + 1, historyRef.current.length - 1);
        setValue(historyRef.current[next] ?? "");
        return next;
      });
      return;
    }
    if (key.downArrow) {
      setHistoryIndex((i) => {
        if (i <= 0) {
          setValue(i === 0 ? "" : historyRef.current[0] ?? "");
          return -1;
        }
        const next = i - 1;
        setValue(historyRef.current[next] ?? "");
        return next;
      });
      return;
    }
  });

  return (
    <Box paddingX={1} flexShrink={0}>
      <Box gap={1}>
        <Text color="cyan">&gt;</Text>
        {(bridgeReady || inputAllowedOverride) && !disabled ? (
          <TextInput
            value={value}
            onChange={setValue}
            onSubmit={submit}
            placeholder={inputAllowedOverride && !bridgeReady ? "Bridge may not be ready – type a task and press Enter" : "Describe your task..."}
            showCursor
          />
        ) : (
          <Text dimColor>
            {!bridgeReady ? "Starting bridge..." : "Waiting for response..."}
          </Text>
        )}
      </Box>
    </Box>
  );
}
