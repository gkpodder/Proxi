import React, { useRef, useEffect } from "react";
import { Box, Text, useStdout } from "ink";
import type { ChatMessage } from "../types.js";
import { FigletTitle, FIGLET_LINE_COUNT } from "./FigletTitle.js";

type Props = {
  messages: ChatMessage[];
  streamingContent: string;
};

export function ChatArea({ messages, streamingContent }: Props) {
  const { stdout } = useStdout();
  const width = stdout.columns - 2;
  const contentLines =
    messages.reduce((acc, m) => acc + wrapLines(m.content, width).length, 0) +
    wrapLines(streamingContent, width).length;
  const totalLines = FIGLET_LINE_COUNT + contentLines;
  const scrollRef = useRef(0);
  const maxVisible = Math.max(1, (stdout.rows ?? 24) - 6);
  const canScroll = totalLines > maxVisible;
  const hasContent = contentLines > 0;

  useEffect(() => {
    if (!canScroll) scrollRef.current = 0;
    else scrollRef.current = Math.max(0, totalLines - maxVisible);
  }, [totalLines, maxVisible, canScroll]);

  const allLines: { role: string; line: string }[] = [];
  for (const m of messages) {
    const lines = wrapLines(m.content, width);
    for (const line of lines) allLines.push({ role: m.role, line });
  }
  for (const line of wrapLines(streamingContent, width)) {
    allLines.push({ role: "assistant", line });
  }

  const start = canScroll ? scrollRef.current : 0;
  const end = start + maxVisible;

  // Figlet occupies lines 0..FIGLET_LINE_COUNT-1. Messages start at FIGLET_LINE_COUNT.
  const figletStart = Math.max(0, start);
  const figletEnd = Math.min(FIGLET_LINE_COUNT, end);
  const figletVisible = figletEnd > figletStart;
  const figletCount = figletVisible ? figletEnd - figletStart : 0;

  const msgStart = Math.max(0, start - FIGLET_LINE_COUNT);
  const msgEnd = Math.max(msgStart, end - FIGLET_LINE_COUNT);
  const visibleMessages = allLines.slice(msgStart, msgEnd);

  return (
    <Box flexDirection="column" overflow="hidden" flexGrow={1}>
      {!hasContent ? (
        <>
          <FigletTitle />
          <Box paddingY={1}>
            <Text dimColor>Enter a task and press Enter. Use ↑/↓ to scroll.</Text>
          </Box>
        </>
      ) : (
        <>
          {figletVisible && (
            <FigletTitle startLine={figletStart} maxLines={figletCount} />
          )}
          {visibleMessages.map(({ role, line }, i) => (
            <Box key={`line-${msgStart}-${i}`}>
              {role === "user" ? (
                <Text color="cyan">&gt; </Text>
              ) : (
                <Text color="green">  </Text>
              )}
              <Text wrap="wrap">{line}</Text>
            </Box>
          ))}
        </>
      )}
    </Box>
  );
}

function wrapLines(text: string, width: number): string[] {
  if (!text.trim()) return [];
  const lines: string[] = [];
  let remaining = text;
  while (remaining.length > 0) {
    if (remaining.length <= width) {
      lines.push(remaining);
      break;
    }
    const chunk = remaining.slice(0, width);
    const lastSpace = chunk.lastIndexOf(" ");
    const breakAt = lastSpace > width >> 1 ? lastSpace : width;
    lines.push(remaining.slice(0, breakAt));
    remaining = remaining.slice(breakAt).replace(/^\s+/, "");
  }
  return lines;
}
