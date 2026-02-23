/**
 * Overlay to view plan.md or todos.md content.
 * Esc to close.
 */
import React, { useState, useEffect } from "react";
import { Box, Text, useInput } from "ink";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";
import { theme } from "../theme.js";

type Props = {
  type: "plan" | "todos";
  agentId: string;
  sessionId: string;
  onDismiss: () => void;
};

function getFilePath(agentId: string, sessionId: string, type: "plan" | "todos"): string {
  const root = process.env.PROXI_HOME
    ? join(process.env.PROXI_HOME.replace(/^~/, homedir()))
    : join(homedir(), ".proxi");
  const filename = type === "plan" ? "plan.md" : "todos.md";
  return join(root, "agents", agentId, "sessions", sessionId, filename);
}

export function PlanTodosOverlay({ type, agentId, sessionId, onDismiss }: Props) {
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    try {
      const path = getFilePath(agentId, sessionId, type);
      const raw = readFileSync(path, "utf-8");
      setContent(raw);
      setError(null);
    } catch (e) {
      const isNotFound =
        e && typeof e === "object" && "code" in e && (e as NodeJS.ErrnoException).code === "ENOENT";
      setContent(null);
      setError(
        isNotFound
          ? type === "plan"
            ? "Plan isn't currently used."
            : "Todos aren't currently used."
          : e instanceof Error
            ? e.message
            : "Failed to read file"
      );
    }
  }, [type, agentId, sessionId]);

  useInput((_input, key) => {
    if (key.escape) {
      onDismiss();
    }
  });

  const title = type === "plan" ? "plan.md" : "todos.md";
  const lines = content ? content.split("\n") : [];
  const maxLines = 15;
  const displayLines = lines.slice(0, maxLines);
  const truncated = lines.length > maxLines;

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor={theme.purpleDim}
      paddingX={1}
      paddingY={0}
      minWidth={50}
    >
      <Box marginBottom={0}>
        <Text color={theme.purple} bold>
          {title}
        </Text>
      </Box>
      <Box flexDirection="column" marginTop={0}>
        {error ? (
          <Box>
            <Text color={theme.rose}>{error}</Text>
          </Box>
        ) : content === null ? (
          <Box>
            <Text color={theme.mist}>Loading...</Text>
          </Box>
        ) : lines.length === 0 ? (
          <Box>
            <Text color={theme.mist}>(empty)</Text>
          </Box>
        ) : (
          <>
            {displayLines.map((line, i) => (
              <Box key={i}>
                <Text color={theme.white}>{line}</Text>
              </Box>
            ))}
            {truncated && (
              <Box>
                <Text color={theme.mist} dimColor>
                  … {lines.length - maxLines} more lines
                </Text>
              </Box>
            )}
          </>
        )}
      </Box>
      <Box marginTop={1}>
        <Text color={theme.mist} dimColor>
          Press Esc to close
        </Text>
      </Box>
    </Box>
  );
}
