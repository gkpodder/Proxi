/**
 * Command palette overlay. Triggered by `/` as first character in input.
 * Filters commands in real-time. ↑/↓ to navigate, Enter to execute, Esc to dismiss.
 */
import React, { useState, useMemo, useCallback } from "react";
import { Box, Text, useInput, useStdout } from "ink";
import TextInput from "ink-text-input";
import { theme } from "../theme.js";

export type CommandDef = {
  id: string;
  name: string;
  description: string;
  handler?: () => void;
};

const COMMANDS: Omit<CommandDef, "handler">[] = [
  { id: "agent", name: "/agent", description: "Switch active agent" },
  { id: "branch", name: "/branch", description: "Clone this agent with current history" },
  { id: "btw", name: "/btw", description: "Quick side session (Esc to return)" },
  { id: "delete", name: "/delete", description: "Delete current agent (gateway + disk)" },
  { id: "mcps", name: "/mcps", description: "Enable or disable MCPs" },
  { id: "work-dir", name: "/work-dir", description: "View or change working directory" },
  { id: "compact", name: "/compact", description: "Summarize context to save tokens (optional: add focus hint)" },
  { id: "clear", name: "/clear", description: "Clear UI + disk history (fresh session)" },
  { id: "plan", name: "/plan", description: "Start an interactive planning session" },
  { id: "reasoning-effort", name: "/reasoning-effort", description: "Set TUI reasoning depth (minimal · medium · high)" },
  { id: "todos", name: "/todos", description: "View open todos" },
  { id: "usage", name: "/usage", description: "Show context and turn usage" },
  { id: "help", name: "/help", description: "Show all commands" },
  { id: "exit", name: "/exit", description: "Exit Proxi" },
];

type Props = {
  onDismiss: () => void;
  onCommand: (cmdId: string) => void;
};

export function CommandPalette({ onDismiss, onCommand }: Props) {
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState(0);
  const { stdout } = useStdout();

  const filtered = useMemo(() => {
    const q = filter.toLowerCase().trim();
    if (!q) return COMMANDS;
    return COMMANDS.filter(
      (c) =>
        c.name.toLowerCase().includes(q) || c.id.toLowerCase().includes(q)
    );
  }, [filter]);

  const maxIdx = Math.max(0, filtered.length - 1);
  const selectedIdx = Math.min(selected, maxIdx);

  const handleSubmit = useCallback(() => {
    if (filtered[selectedIdx]) {
      onCommand(filtered[selectedIdx]!.id);
      onDismiss();
    }
  }, [filtered, selectedIdx, onCommand, onDismiss]);

  // useInput for escape + arrows only; TextInput handles typing/backspace/delete/enter
  useInput((_input, key) => {
    if (key.escape) {
      onDismiss();
      return;
    }
    if (key.upArrow) {
      setSelected((i) => (i <= 0 ? maxIdx : i - 1));
      return;
    }
    if (key.downArrow) {
      setSelected((i) => (i >= maxIdx ? 0 : i + 1));
      return;
    }
  });

  const termWidth = stdout?.columns ?? 80;
  const prefixWidth = 3; // "›  " or "   "
  const nameWidth = 18; // enough for "/reasoning-effort" without wrapping
  const descMinWidth = 16;
  const descWidth = Math.max(descMinWidth, termWidth - (2 + prefixWidth + nameWidth)); // +2 for container paddingX

  const truncate = (s: string, w: number) => {
    if (w <= 0) return "";
    if (s.length <= w) return s;
    if (w === 1) return "…";
    return s.slice(0, Math.max(0, w - 1)) + "…";
  };

  const formatNameCol = (name: string) => {
    if (name.length >= nameWidth) return truncate(name, nameWidth);
    return name.padEnd(nameWidth);
  };

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor={theme.purpleDim}
      paddingX={1}
      paddingY={0}
      minWidth={44}
    >
      <Box marginBottom={0}>
        <Text color={theme.purple}>/</Text>
        <Text color={theme.purple}> </Text>
        <TextInput
          value={filter}
          onChange={(v) => {
            setFilter(v);
            setSelected(0);
          }}
          onSubmit={handleSubmit}
          placeholder="filter commands..."
          showCursor
        />
      </Box>
      <Box flexDirection="column">
        {filtered.length === 0 ? (
          <Box>
            <Text color={theme.mist}>   No commands match</Text>
          </Box>
        ) : (
          filtered.map((cmd, i) => (
            <Box key={cmd.id}>
              <Text
                color={i === selectedIdx ? theme.purple : undefined}
                backgroundColor={i === selectedIdx ? theme.purpleFaint : undefined}
              >
                {i === selectedIdx ? "›  " : "   "}
              </Text>
              <Text
                color={theme.white}
                backgroundColor={i === selectedIdx ? theme.purpleFaint : undefined}
              >
                {formatNameCol(cmd.name)}
              </Text>
              <Text
                color={theme.mist}
                backgroundColor={i === selectedIdx ? theme.purpleFaint : undefined}
              >
                {truncate(cmd.description, descWidth)}
              </Text>
            </Box>
          ))
        )}
      </Box>
    </Box>
  );
}

export { COMMANDS };
