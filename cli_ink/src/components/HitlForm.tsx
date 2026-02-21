import React, { useState, useCallback, useRef, useEffect } from "react";
import { Box, Text, useInput } from "ink";
import TextInput from "ink-text-input";
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
      <Box paddingX={1} flexShrink={0} gap={1}>
        <Text color="yellow">{(spec.prompt ?? "Confirm?")}</Text>
        <Box gap={1}>
          <Text bold color="green" underline>
            Y
          </Text>
          <Text> Yes</Text>
          <Text dimColor> N No (Esc cancel)</Text>
        </Box>
      </Box>
    );
  }

  if (spec.method === "select" && options.length > 0) {
    return (
      <Box paddingX={1} flexDirection="column" flexShrink={0} gap={0}>
        <Text color="yellow">{spec.prompt ?? "Choose one:"}</Text>
        {options.map((opt, i) => (
          <Box key={opt}>
            <Text color={i === selectIndex ? "green" : "white"}>
              {i === selectIndex ? "› " : "  "}
              {opt}
            </Text>
          </Box>
        ))}
        <Text dimColor> Enter confirm · ↑↓ select · Esc cancel</Text>
      </Box>
    );
  }

  if (spec.method === "text") {
    return (
      <Box paddingX={1} flexShrink={0} gap={1}>
        <Text color="yellow">{(spec.prompt ?? "Enter value:")}</Text>
        <TextInput
          value={textValue}
          onChange={setTextValue}
          onSubmit={() => handleSubmit()}
          placeholder=""
          showCursor
        />
        <Text dimColor> Esc cancel</Text>
      </Box>
    );
  }

  return (
    <Box paddingX={1}>
      <Text dimColor>Unknown input method</Text>
    </Box>
  );
}
