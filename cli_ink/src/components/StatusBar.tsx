import React from "react";
import { Box, Text } from "ink";
import Spinner from "ink-spinner";
import { theme } from "../theme.js";

type StatusKind = "tool" | "subagent" | "progress" | null;

type Props = {
  statusLabel: string | null;
  statusKind: StatusKind;
  isProgress: boolean;
  agentId?: string;
  sessionId?: string;
  isWaitingForInput?: boolean;
};

export function StatusBar({
  statusLabel,
  statusKind,
  isProgress,
  agentId,
  sessionId,
  isWaitingForInput,
}: Props) {
  const showTool = statusKind === "tool" && statusLabel;
  const showSubagent = statusKind === "subagent" && statusLabel;
  const showProgress = (statusKind === "progress" || (statusLabel && !showTool && !showSubagent)) && statusLabel;

  // Status word per spec: ready (mint), thinking (purpleDim), acting (peach), waiting for input (purple)
  let statusWord: string;
  let statusColor: string;
  if (isWaitingForInput) {
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
      <Text color={theme.purpleDim}>  ·  </Text>
      <Text color={statusColor}>{statusWord}</Text>
      {(showTool || showSubagent || showProgress) && isProgress && (
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
        <Text color={theme.mist}>↑↓ scroll  /  commands</Text>
      </Box>
    </Box>
  );
}
