import React, { useState, useCallback, useRef, useEffect } from "react";
import { Box, Text, useInput } from "ink";
import TextInput from "ink-text-input";
import { theme } from "../theme.js";
import type { UserInputRequiredBootstrap } from "../protocol.js";

type Props = {
  spec: UserInputRequiredBootstrap;
  onSubmit: (value: string | boolean | number) => void;
  onCancel: () => void;
};

export function HitlForm({ spec, onSubmit, onCancel }: Props) {
  const [selectIndex, setSelectIndex] = useState(0);
  const [textValue, setTextValue] = useState("");
  const selectIndexRef = useRef(selectIndex);
  useEffect(() => {
    selectIndexRef.current = selectIndex;
  }, [selectIndex]);

  const options = spec.options ?? [];
  const maxIndex = Math.max(0, options.length - 1);
  const workDirMatch =
    spec.method === "text"
      ? (spec.prompt ?? "").match(
          /^Working dir:\s*(.+)\nEnter new path \(leave empty to cancel\):$/
        )
      : null;
  const currentWorkDir = workDirMatch?.[1] ?? "";

  useEffect(() => {
    setTextValue("");
    setSelectIndex(0);
  }, [spec.prompt, spec.method, spec.ui]);

  useInput((input, key) => {
    if (key.escape) {
      onCancel();
      return;
    }
    if (spec.method === "confirm") {
      if (input.toLowerCase() === "y") onSubmit(true);
      if (input.toLowerCase() === "n") onSubmit(false);
      return;
    }
    if (spec.method === "select" && options.length > 0) {
      if (key.upArrow) setSelectIndex((i) => (i <= 0 ? maxIndex : i - 1));
      if (key.downArrow) setSelectIndex((i) => (i >= maxIndex ? 0 : i + 1));
      if (key.return) {
        const idx = selectIndexRef.current;
        if (options[idx] !== undefined) onSubmit(options[idx] as string);
      }
    }
  });

  const handleSubmit = useCallback(() => {
    if (spec.method === "confirm") {
      onSubmit(true);
      return;
    }
    if (spec.method === "select" && options[selectIndex] !== undefined) {
      onSubmit(options[selectIndex] as string);
      return;
    }
    if (spec.method === "text") {
      onSubmit(textValue);
      return;
    }
  }, [spec.method, spec.options, selectIndex, textValue, onSubmit]);

  if (spec.method === "confirm") {
    return (
      <Box
        paddingX={1}
        flexShrink={0}
        gap={1}
        borderStyle="round"
        borderColor={theme.purpleDim}
      >
        <Text color={theme.purple} bold>
          {(spec.prompt ?? "Confirm?")}
        </Text>
        <Box gap={1}>
          <Text bold color={theme.mint} underline>
            Y
          </Text>
          <Text color={theme.white}> Yes</Text>
          <Text color={theme.mist}> N No (Esc cancel)</Text>
        </Box>
      </Box>
    );
  }

  if (spec.method === "select" && options.length > 0) {
    if (spec.ui === "reasoning-effort") {
      return (
        <Box
          paddingX={1}
          paddingY={0}
          flexDirection="column"
          flexShrink={0}
          gap={0}
          borderStyle="round"
          borderColor={theme.purpleDim}
        >
          <Box marginBottom={1}>
            <Text color={theme.peach} bold>
              ◆ Reasoning effort
            </Text>
            <Text color={theme.purpleDim}>  ·  </Text>
            <Text color={theme.mist}>TUI-only</Text>
          </Box>

          <Box flexDirection="column" marginBottom={1}>
            <Text color={theme.mist}>Choose how much reasoning the agent should use in this session.</Text>
            <Text color={theme.mist}>This does not affect cron, Discord, or other sources.</Text>
          </Box>

          <Box flexDirection="column" marginBottom={1}>
            <Text color={theme.lavender}>Level</Text>
            {options.map((opt, i) => (
              <Box key={opt}>
                <Text
                  color={i === selectIndex ? theme.purple : theme.white}
                  backgroundColor={i === selectIndex ? theme.purpleFaint : undefined}
                >
                  {i === selectIndex ? "› " : "  "}
                  {opt}
                </Text>
              </Box>
            ))}
          </Box>

          <Text color={theme.mist} dimColor>
            Enter — apply · ↑↓ select · Esc — cancel
          </Text>
        </Box>
      );
    }
    return (
      <Box
        paddingX={1}
        flexDirection="column"
        flexShrink={0}
        gap={0}
        borderStyle="round"
        borderColor={theme.purpleDim}
      >
        <Text color={theme.purple} bold>
          {spec.prompt ?? "Choose one:"}
        </Text>
        {options.map((opt, i) => (
          <Box key={opt}>
            <Text
              color={i === selectIndex ? theme.purple : theme.white}
              backgroundColor={i === selectIndex ? theme.purpleFaint : undefined}
            >
              {i === selectIndex ? "› " : "  "}
              {opt}
            </Text>
          </Box>
        ))}
        <Text color={theme.mist}> Enter confirm · ↑↓ select · Esc cancel</Text>
      </Box>
    );
  }

  if (spec.method === "text") {
    if (spec.ui === "reasoning-effort") {
      return (
        <Box
          paddingX={1}
          paddingY={0}
          flexDirection="column"
          flexShrink={0}
          borderStyle="round"
          borderColor={theme.purpleDim}
          gap={0}
        >
          <Box marginBottom={1}>
            <Text color={theme.peach} bold>
              ◆ Reasoning effort
            </Text>
          </Box>
          <Box flexDirection="column" marginBottom={1}>
            <Text color={theme.mist}>
              Set the reasoning depth for your TUI prompts this session.
            </Text>
            <Text color={theme.mist}>
              Cron, Discord, and other sources are unaffected.
            </Text>
          </Box>
          <Box marginBottom={0}>
            <Text color={theme.lavender}>Level</Text>
          </Box>
          <Box marginBottom={1}>
            <Text color={theme.purple} bold>
              {"› "}
            </Text>
            <TextInput
              key="reasoning-effort-hitl"
              value={textValue}
              onChange={setTextValue}
              onSubmit={() => handleSubmit()}
              placeholder="minimal · low · medium · high"
              showCursor
            />
          </Box>
          <Box flexDirection="row" justifyContent="space-between">
            <Text color={theme.mist} dimColor>
              Enter — apply · Esc — cancel
            </Text>
          </Box>
        </Box>
      );
    }
    if (spec.ui === "compact") {
      return (
        <Box
          paddingX={1}
          paddingY={0}
          flexDirection="column"
          flexShrink={0}
          borderStyle="round"
          borderColor={theme.purpleDim}
          gap={0}
        >
          <Box marginBottom={1}>
            <Text color={theme.purple} bold>
              Compact context
            </Text>
          </Box>
          <Box flexDirection="column" marginBottom={1}>
            <Text color={theme.mist}>
              Roll up older conversation into a summary so the next turns use fewer
              tokens.
            </Text>
            <Text color={theme.mist}>
              Optional: name topics, files, or decisions you want the summary to
              preserve.
            </Text>
          </Box>
          <Box marginBottom={0}>
            <Text color={theme.lavender}>Focus hint</Text>
            <Text color={theme.purpleDim}> </Text>
            <Text color={theme.mist} italic>
              (leave empty for default)
            </Text>
          </Box>
          <Box marginBottom={1}>
            <Text color={theme.purple} bold>
              ›{" "}
            </Text>
            <TextInput
              key="compact-hitl"
              value={textValue}
              onChange={setTextValue}
              onSubmit={() => handleSubmit()}
              placeholder="e.g. auth refactor, proxi/gateway/server.py, open bugs…"
              showCursor
            />
          </Box>
          <Box flexDirection="row" justifyContent="space-between">
            <Text color={theme.mist}>Enter — run compaction · Esc — cancel</Text>
          </Box>
        </Box>
      );
    }
    if (spec.ui === "plan") {
      return (
        <Box
          paddingX={1}
          paddingY={0}
          flexDirection="column"
          flexShrink={0}
          borderStyle="round"
          borderColor={theme.purpleDim}
          gap={0}
        >
          <Box marginBottom={1}>
            <Text color={theme.purple} bold>
              ◆ Plan mode
            </Text>
          </Box>
          <Box flexDirection="column" marginBottom={1}>
            <Text color={theme.mist}>
              Describe your goal. The agent will interview you, explore the codebase,
            </Text>
            <Text color={theme.mist}>
              and write a structured plan for you to review before any changes are made.
            </Text>
          </Box>
          <Box marginBottom={0}>
            <Text color={theme.lavender}>Goal</Text>
          </Box>
          <Box marginBottom={1}>
            <Text color={theme.purple} bold>
              ›{" "}
            </Text>
            <TextInput
              key="plan-hitl"
              value={textValue}
              onChange={setTextValue}
              onSubmit={() => handleSubmit()}
              placeholder="e.g. implement OAuth2 login, refactor the gateway, add dark mode…"
              showCursor
            />
          </Box>
          <Box flexDirection="row" justifyContent="space-between">
            <Text color={theme.mist}>Enter — start planning · Esc — cancel</Text>
          </Box>
        </Box>
      );
    }
    if (workDirMatch) {
      return (
        <Box
          paddingX={1}
          flexDirection="column"
          flexShrink={0}
          borderStyle="round"
          borderColor={theme.purpleDim}
        >
          <Box marginBottom={1}>
            <Text color={theme.purple} bold>
              Working Directory
            </Text>
          </Box>
          <Box marginBottom={1}>
            <Text color={theme.mist}>Current</Text>
            <Text color={theme.purple}>  </Text>
            <Text color={theme.white} backgroundColor={theme.purpleFaint}>
              {` ${currentWorkDir} `}
            </Text>
          </Box>
          <Box marginBottom={0}>
            <Text color={theme.lavender}>New path</Text>
          </Box>
          <Box marginBottom={1}>
            <Text color={theme.purple}>&gt;</Text>
            <Text color={theme.purple}> </Text>
            <TextInput
              key={spec.prompt ?? "text"}
              value={textValue}
              onChange={setTextValue}
              onSubmit={() => handleSubmit()}
              placeholder="Enter absolute or relative path..."
              showCursor
            />
          </Box>
          <Text color={theme.mist}>Enter to save · Esc to cancel</Text>
        </Box>
      );
    }

    return (
      <Box
        paddingX={1}
        flexShrink={0}
        gap={1}
        borderStyle="round"
        borderColor={theme.purpleDim}
      >
        <Text color={theme.purple} bold>
          {(spec.prompt ?? "Enter value:")}
        </Text>
        <TextInput
          key={spec.ui ? `ui-${spec.ui}` : (spec.prompt ?? "text")}
          value={textValue}
          onChange={setTextValue}
          onSubmit={() => handleSubmit()}
          placeholder=""
          showCursor
        />
        <Text color={theme.mist}> Esc cancel</Text>
      </Box>
    );
  }

  return (
    <Box paddingX={1}>
      <Text color={theme.mist}>Unknown input method</Text>
    </Box>
  );
}
