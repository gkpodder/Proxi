import React from "react";
import { Box, Text } from "ink";
import Spinner from "ink-spinner";
type StatusKind = "tool" | "subagent" | "progress" | null;

type Props = {
  statusLabel: string | null;
  statusKind: StatusKind;
  isProgress: boolean;
};

export function StatusBar({ statusLabel, statusKind, isProgress }: Props) {
  const showTool = statusKind === "tool" && statusLabel;
  const showSubagent = statusKind === "subagent" && statusLabel;
  const showProgress = (statusKind === "progress" || (statusLabel && !showTool && !showSubagent)) && statusLabel;

  return (
    <Box paddingX={1} paddingY={0} height={1} flexShrink={0}>
      <Box gap={1}>
        {showTool && (
          <Text color="yellow">
            🛠️ Running: {statusLabel.replace(/^Tool:\s*/, "")}
            {isProgress && (
              <>
                {" "}
                <Spinner type="dots" />
              </>
            )}
          </Text>
        )}
        {showSubagent && (
          <Text color="magenta">
            🤖 {statusLabel}
            {isProgress && (
              <>
                {" "}
                <Spinner type="dots" />
              </>
            )}
          </Text>
        )}
        {showProgress && (
          <Text color="cyan">
            {statusLabel}
            {isProgress && (
              <>
                {" "}
                <Spinner type="dots" />
              </>
            )}
          </Text>
        )}
        {!statusLabel && (
          <Text dimColor> Ready</Text>
        )}
      </Box>
    </Box>
  );
}
