import React, { useMemo } from "react";
import { Box, Text, useInput } from "ink";
import { theme } from "../theme.js";

type UsageStats = {
  tokens_used: number;
  token_budget: number;
  context_window: number;
  turns_used: number;
  max_turns: number;
};

type Props = {
  stats: UsageStats;
  onDismiss: () => void;
};

function makeBar(used: number, total: number, width = 24): { bar: string; pct: number } {
  const pct = total > 0 ? Math.round((used / total) * 100) : 0;
  const clampedPct = Math.max(0, Math.min(100, pct));
  const fill = Math.round((clampedPct / 100) * width);
  return { bar: "█".repeat(fill) + "░".repeat(width - fill), pct: clampedPct };
}

export function UsageOverlay({ stats, onDismiss }: Props) {
  useInput((input, key) => {
    if (key.escape || key.return || input.toLowerCase() === "q") {
      onDismiss();
    }
  });

  const context = useMemo(
    () => makeBar(stats.tokens_used, stats.token_budget),
    [stats.tokens_used, stats.token_budget]
  );
  const turns = useMemo(
    () => makeBar(stats.turns_used, stats.max_turns),
    [stats.turns_used, stats.max_turns]
  );

  const fmt = (n: number) => n.toLocaleString();

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor={theme.purpleDim}
      paddingX={1}
      minWidth={66}
    >
      <Box marginBottom={1}>
        <Text color={theme.purple} bold>
          Session Usage
        </Text>
      </Box>

      <Box marginBottom={0}>
        <Text color={theme.mist}>Context</Text>
      </Box>
      <Box marginBottom={1}>
        <Text color={theme.white}>[{context.bar}]</Text>
        <Text color={theme.purple}>  {String(context.pct).padStart(3)}%</Text>
        <Text color={theme.mist}>
          {" "}
          {fmt(stats.tokens_used)} / {fmt(stats.token_budget)} tokens
        </Text>
      </Box>
      <Box marginBottom={1}>
        <Text color={theme.mist}>Window: {fmt(stats.context_window)}</Text>
      </Box>

      <Box marginBottom={0}>
        <Text color={theme.mist}>Turns</Text>
      </Box>
      <Box marginBottom={1}>
        <Text color={theme.white}>[{turns.bar}]</Text>
        <Text color={theme.purple}>  {String(turns.pct).padStart(3)}%</Text>
        <Text color={theme.mist}>
          {" "}
          {stats.turns_used} / {stats.max_turns} turns
        </Text>
      </Box>

      <Text color={theme.mist}>Esc, Enter, or q to close</Text>
    </Box>
  );
}
