import React from "react";
import { Box, Text } from "ink";
import Spinner from "ink-spinner";
import { theme } from "../theme.js";

type StatusKind = "tool" | "subagent" | "progress" | null;

type Props = {
  statusLabel: string | null;
  statusKind: StatusKind;
  isProgress: boolean;
  /** When set, shows the dots spinner (e.g. TUI user turn or tui_abortable work). */
  showSpinner?: boolean;
  /** Show Esc-abort hint for in-flight TUI turns (not background cron/heartbeat). */
  showAbortHint?: boolean;
  agentId?: string;
  sessionId?: string;
  isWaitingForInput?: boolean;
  isBtw?: boolean;
  isCompacting?: boolean;
  isPlanMode?: boolean;
  autoCompactPercent?: number | null;
};

export function StatusBar({
  statusLabel,
  statusKind,
  isProgress,
  showSpinner,
  showAbortHint,
  agentId,
  sessionId,
  isWaitingForInput,
  isBtw,
  isCompacting,
  isPlanMode,
  autoCompactPercent,
}: Props) {
  const showTool = statusKind === "tool" && statusLabel;
  const showSubagent = statusKind === "subagent" && statusLabel;
  const showProgress = (statusKind === "progress" || (statusLabel && !showTool && !showSubagent)) && statusLabel;

  // Status word per spec: ready (mint), thinking (purpleDim), acting (peach), waiting for input (purple)
  let statusWord: string;
  let statusColor: string;
  if (isPlanMode) {
    statusWord = "planning";
    statusColor = theme.lavender;
  } else if (isCompacting) {
    statusWord = "compacting";
    statusColor = theme.peach;
  } else if (isWaitingForInput) {
    statusWord = "waiting for input";
    statusColor = theme.purple;
  } else if (showTool || showSubagent || showProgress) {
    statusWord = "acting";
    statusColor = theme.peach;
  } else if (statusLabel && !showTool && !showSubagent && statusLabel.toLowerCase().includes("thinking")) {
    statusWord = "thinking";
    statusColor = theme.purpleDim;
  } else {
    statusWord = "ready";
    statusColor = theme.mint;
  }

  const leftContent = (
    <Box>
      <Text>  </Text>
      <Text color={theme.purple}>◆ {agentId ?? "—"}</Text>
      <Text color={theme.purpleDim}>  ·  </Text>
      <Text color={theme.mist}>session {sessionId ?? "—"}</Text>
      {isBtw && (
        <>
          <Text color={theme.purpleDim}>  ·  </Text>
          <Text color={theme.peach} bold>btw</Text>
        </>
      )}
      {isPlanMode && (
        <>
          <Text color={theme.purpleDim}>  ·  </Text>
          <Text color={theme.lavender} bold>◆ plan</Text>
        </>
      )}
      <Text color={theme.purpleDim}>  ·  </Text>
      <Text color={statusColor}>{statusWord}</Text>
      {(showSpinner ?? ((showTool || showSubagent || showProgress) && isProgress)) && (
        <>
          <Text> </Text>
          <Spinner type="dots" />
        </>
      )}
    </Box>
  );

  return (
    <Box paddingX={1} paddingY={0} height={1} flexShrink={0} justifyContent="space-between">
      <Box>{leftContent}</Box>
      <Box>
        {isBtw && (
          <>
            <Text color={theme.peach} bold>Esc return</Text>
            <Text color={theme.purpleDim}> · </Text>
          </>
        )}
        {!isBtw && showAbortHint && (
          <>
            <Text color="red" bold>
              Esc abort
            </Text>
            <Text color={theme.purpleDim}> · </Text>
          </>
        )}
        {autoCompactPercent !== null && autoCompactPercent !== undefined && (
          <>
            <Text color={theme.mist}>{autoCompactPercent}% context remaining</Text>
            <Text color={theme.purpleDim}> · </Text>
          </>
        )}
        <Text color={theme.mist}>↑↓ scroll  /  commands</Text>
      </Box>
    </Box>
  );
}
