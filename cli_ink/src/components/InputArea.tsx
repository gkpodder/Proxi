import React, { useState, useCallback, useRef } from "react";
import { Box, Text, useInput } from "ink";
import TextInput from "ink-text-input";
import { theme } from "../theme.js";

type Props = {
  onSubmit: (task: string, provider: "openai" | "anthropic", maxTurns: number) => void;
  onCommitStreaming: () => void;
  disabled: boolean;
  bridgeReady: boolean;
  inputAllowedOverride?: boolean;
  onSwitchAgent?: () => void;
  onAbort?: () => void;
  onOpenCommandPalette?: () => void;
  isRunning?: boolean;
  inputHistory?: string[];
};

export function InputArea({
  onSubmit,
  onCommitStreaming,
  disabled,
  bridgeReady,
  inputAllowedOverride = false,
  onSwitchAgent,
  onAbort,
  onOpenCommandPalette,
  isRunning = false,
  inputHistory = [],
}: Props) {
  const [value, setValue] = useState("");
  const [historyIndex, setHistoryIndex] = useState(-1);
  const historyRef = useRef<string[]>([]);
  historyRef.current = inputHistory;

  const submit = useCallback(() => {
    const task = value.trim();
    if (!task) return;
    if (task === "/agent" || task === "/switch-agent") {
      onSwitchAgent?.();
      setValue("");
      return;
    }
    onCommitStreaming();
    onSubmit(task, "openai", 50);
    setValue("");
    setHistoryIndex(-1);
  }, [value, onSubmit, onCommitStreaming, onSwitchAgent]);

  const canInput = (bridgeReady || inputAllowedOverride) && !disabled;

  useInput((input, key) => {
    if (key.escape) {
      if (isRunning && onAbort) onAbort();
      return;
    }
    if (!canInput) return;
    if (value === "" && input === "/" && onOpenCommandPalette) {
      onOpenCommandPalette();
      return;
    }
    if ((key.upArrow || key.downArrow) && historyRef.current.length > 0) {
      if (key.upArrow) {
        setHistoryIndex((i) => {
          const next = i === -1 ? 0 : Math.min(i + 1, historyRef.current.length - 1);
          setValue(historyRef.current[next] ?? "");
          return next;
        });
      } else {
        setHistoryIndex((i) => {
          if (i === -1) return -1;
          if (i <= 0) {
            setValue("");
            return -1;
          }
          const next = i - 1;
          setValue(historyRef.current[next] ?? "");
          return next;
        });
      }
    }
  });

  const placeholder =
    inputAllowedOverride && !bridgeReady
      ? "Bridge may not be ready – type a task and press Enter"
      : "Describe your task...";

  return (
    <Box paddingX={1} flexShrink={0}>
      <Box gap={1}>
        <Text color={theme.purple}>&gt;</Text>
        <Text color={theme.purple}> </Text>
        {canInput ? (
          <TextInput
            value={value}
            onChange={setValue}
            onSubmit={submit}
            placeholder={placeholder}
            showCursor
          />
        ) : (
          <Box gap={1}>
            <Text dimColor>
              {!bridgeReady ? "Starting bridge..." : "Waiting for response..."}
            </Text>
            {isRunning && onAbort && (
              <Text color="red" bold>
                [Esc: Abort]
              </Text>
            )}
          </Box>
        )}
      </Box>
    </Box>
  );
}
