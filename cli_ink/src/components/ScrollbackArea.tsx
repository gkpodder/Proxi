/**
 * Zone A (scrollback) — Figlet title + all messages from top, chronological order.
 */
import React from "react";
import { Box, Text, Newline } from "ink";
import Spinner from "ink-spinner";
import { theme } from "../theme.js";
import type { ScrollbackItem } from "../types/scrollback.js";
import { FigletTitle } from "./FigletTitle.js";

function prettyInboundSourceType(st: string): string {
  const map: Record<string, string> = {
    heartbeat: "Heartbeat",
    cron: "Cron",
    webhook: "Webhook",
    telegram: "Telegram",
    whatsapp: "WhatsApp",
    discord: "Discord",
    http: "HTTP",
  };
  return map[st] ?? (st.length ? st.charAt(0).toUpperCase() + st.slice(1) : st);
}

function formatToolInvocation(tool: string, args: Record<string, unknown> | undefined): string {
  if (!args || Object.keys(args).length === 0) return `${tool}()`;
  const entries = Object.entries(args);
  if (entries.length === 1) {
    const val = entries[0]![1];
    if (typeof val === "string" && val.length <= 80) {
      return `${tool}("${String(val).replace(/"/g, '\\"')}")`;
    }
  }
  const argsStr = JSON.stringify(args);
  if (argsStr.length <= 60) return `${tool}(${argsStr})`;
  return `${tool}(...)`;
}

function isBlockEnder(item: ScrollbackItem | undefined): boolean {
  if (!item) return false;
  if (item.type === "tool_done") return true;
  if (item.type === "subagent" && item.status === "done") return true;
  return false;
}

function needsBlockSpacingBefore(item: ScrollbackItem, prevItem: ScrollbackItem | undefined): boolean {
  if (!prevItem) return false;
  if (!isBlockEnder(prevItem)) return false;
  return (
    item.type === "tool_start" ||
    item.type === "subagent" ||
    item.type === "agent_line" ||
    item.type === "inbound_turn_header"
  );
}

function renderItem(item: ScrollbackItem, index: number, prevItem: ScrollbackItem | undefined) {
  switch (item.type) {
    case "user":
      return (
        <Box key={index} paddingX={1}>
          <Text backgroundColor={theme.purpleFaint} color={theme.purple}>
            {"  > "}{item.content}
          </Text>
        </Box>
      );
    case "inbound_turn_header": {
      const label = prettyInboundSourceType(item.sourceType);
      return (
        <Box key={index} marginLeft={1} marginRight={1}>
          <Box
            flexDirection="column"
            borderStyle="round"
            borderColor={theme.purpleDim}
            paddingX={1}
            paddingY={0}
          >
            <Box flexDirection="row" flexWrap="wrap" alignItems="center">
              <Text color={theme.purpleDim}>⏱ </Text>
              <Text color={theme.lavender} bold>
                {label}
              </Text>
              {item.sourceId ? (
                <>
                  <Text color={theme.mist}> · </Text>
                  <Text color={theme.purpleDim}>{item.sourceId}</Text>
                </>
              ) : null}
            </Box>
            <Box marginTop={1}>
              <Text backgroundColor={theme.purpleFaint} color={theme.purple}>
                {"  > "}
              </Text>
              <Text backgroundColor={theme.purpleFaint} color={theme.lavender}>
                {item.prompt}
              </Text>
            </Box>
          </Box>
        </Box>
      );
    }
    case "spacing":
      return (
        <Box key={index}>
          <Newline />
        </Box>
      );
    case "agent_line": {
      const c = item.isSystem ? theme.mist : theme.white;
      return (
        <Box key={index}>
          <Text color={c}>  {item.isFirst ? "⏺" : " "} </Text>
          <Text color={c}>{item.content}</Text>
        </Box>
      );
    }
    case "agent_blank":
      return (
        <Box key={index}>
          <Newline />
        </Box>
      );
    case "tool_start": {
      const inv = formatToolInvocation(item.tool, item.args);
      return (
        <Box key={index}>
          <Text color={theme.purpleDim}>  🛠️  </Text>
          <Text color={theme.white}>{inv}</Text>
        </Box>
      );
    }
    case "tool_log":
      return (
        <Box key={index}>
          <Text color={theme.mist}>  ⎿  </Text>
          <Text color={theme.mist}>{item.content}</Text>
        </Box>
      );
    case "tool_done":
      return (
        <Box key={index}>
          <Text color={item.success ? theme.mint : theme.rose}>
            {"  🛠️  "}
            {item.success ? "✓ done" : `✗ failed${item.error ? ` ${item.error}` : ""}`}
          </Text>
        </Box>
      );
    case "subagent": {
      const isDone = item.status === "done";
      const success = isDone ? item.success : true;
      return (
        <Box key={index}>
          {isDone ? (
            <Text color={success ? theme.mint : theme.rose}>
              {"  🤖  "}sub-agent {item.agent} {success ? "✓ done" : "✗ failed"}
            </Text>
          ) : (
            <>
              <Text color={theme.purpleDim}>  🤖  </Text>
              <Text color={theme.white}>sub-agent {item.agent} </Text>
              <Text color={theme.purpleDim}>
                {" "}
                <Spinner type="line" />
                {" "}running...
              </Text>
            </>
          )}
        </Box>
      );
    }
    default:
      return null;
  }
}

type Props = {
  items: ScrollbackItem[];
  streamingContent: string;
};

export function ScrollbackArea({ items, streamingContent }: Props) {
  return (
    <Box flexDirection="column" flexGrow={1} minHeight={1}>
      <Box marginBottom={1}>
        <FigletTitle />
      </Box>
      {items.map((item, i) => {
        const prev = i > 0 ? items[i - 1] : undefined;
        const spacer = needsBlockSpacingBefore(item, prev);
        return (
          <React.Fragment key={i}>
            {spacer && (
              <Box>
                <Newline />
              </Box>
            )}
            {renderItem(item, i, prev)}
          </React.Fragment>
        );
      })}
      {streamingContent.length > 0 && (
        <Box>
          <Text color={theme.white}>  ⏺ </Text>
          <Text color={theme.white}>{streamingContent}</Text>
          <Text color={theme.purpleDim}>▌</Text>
        </Box>
      )}
    </Box>
  );
}
