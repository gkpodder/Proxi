/**
 * Rich interactive overlay shown when the agent finishes writing a plan.
 * Supports scrolling, markdown rendering (headers / bullets / checkboxes /
 * fenced code blocks / inline code), and Accept / Refine / Reject actions.
 */
import React, { useState, useCallback, useMemo } from "react";
import { Box, Text, useInput, useStdout } from "ink";
import TextInput from "ink-text-input";
import { theme } from "../theme.js";

type Props = {
  content: string;
  planPath?: string;
  activePlanPath?: string;
  onAccept: () => void;
  onRefine: (feedback: string) => void;
  onReject: () => void;
};

type FooterMode = "idle" | "refining";

// ---------------------------------------------------------------------------
// Line kind classification — needed for fenced code block detection
// ---------------------------------------------------------------------------
type LineKind = "normal" | "fence" | "code";

function computeLineKinds(lines: string[]): LineKind[] {
  const kinds: LineKind[] = [];
  let inCode = false;
  for (const line of lines) {
    if (/^```/.test(line)) {
      kinds.push("fence");
      inCode = !inCode;
    } else if (inCode) {
      kinds.push("code");
    } else {
      kinds.push("normal");
    }
  }
  return kinds;
}

// ---------------------------------------------------------------------------
// Inline code span renderer — splits on `backtick spans` within a line
// ---------------------------------------------------------------------------
function renderInlineSpans(text: string, baseColor: string): React.ReactNode {
  const segments = text.split(/(`[^`]+`)/);
  if (segments.length === 1) {
    return <Text color={baseColor}>{text}</Text>;
  }
  return (
    <>
      {segments.map((seg, i) =>
        seg.length > 2 && seg.startsWith("`") && seg.endsWith("`") ? (
          <Text key={i} color={theme.peach}>
            {seg.slice(1, -1)}
          </Text>
        ) : (
          <Text key={i} color={baseColor}>
            {seg}
          </Text>
        )
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Fenced code block line renderers
// ---------------------------------------------------------------------------
function renderFenceLine(line: string, index: number): React.ReactNode {
  const lang = line.trim().replace(/^`+/, "").trim();
  if (lang) {
    // Opening fence with language label
    const dashes = "─".repeat(Math.max(0, 52 - lang.length));
    return (
      <Text key={index}>
        <Text color={theme.purpleDim}>{"─── "}</Text>
        <Text color={theme.mist}>{lang}</Text>
        <Text color={theme.purpleDim}>{" " + dashes}</Text>
      </Text>
    );
  }
  // Closing fence (or opening without language)
  return (
    <Text key={index} color={theme.purpleDim}>
      {"─".repeat(56)}
    </Text>
  );
}

function renderCodeLine(line: string, index: number): React.ReactNode {
  return (
    <Text key={index}>
      <Text color={theme.purpleDim}>{"▎ "}</Text>
      <Text color={theme.mint}>{line}</Text>
    </Text>
  );
}

// ---------------------------------------------------------------------------
// Normal markdown line renderer (headers / bullets / checkboxes / plain)
// ---------------------------------------------------------------------------
function renderMarkdownLine(line: string, index: number): React.ReactNode {
  // H1
  if (/^# /.test(line)) {
    return (
      <Text key={index} color={theme.purple} bold>
        {renderInlineSpans(line.slice(2), theme.purple)}
      </Text>
    );
  }
  // H2
  if (/^## /.test(line)) {
    return (
      <Text key={index} color={theme.purple} bold>
        {renderInlineSpans(line.slice(3), theme.purple)}
      </Text>
    );
  }
  // H3
  if (/^### /.test(line)) {
    return (
      <Text key={index} color={theme.lavender} bold>
        {renderInlineSpans(line.slice(4), theme.lavender)}
      </Text>
    );
  }
  // Checked checkbox
  if (/^- \[x\] /i.test(line)) {
    return (
      <Text key={index} color={theme.mint}>
        {"  ✓ "}
        {renderInlineSpans(line.slice(6), theme.mint)}
      </Text>
    );
  }
  // Unchecked checkbox
  if (/^- \[ \] /.test(line)) {
    return (
      <Text key={index} color={theme.white}>
        {"  ○ "}
        {renderInlineSpans(line.slice(6), theme.white)}
      </Text>
    );
  }
  // Bullet
  if (/^[-*] /.test(line)) {
    return (
      <Text key={index} color={theme.white}>
        {"  · "}
        {renderInlineSpans(line.slice(2), theme.white)}
      </Text>
    );
  }
  // Numbered list
  if (/^\d+\. /.test(line)) {
    const match = line.match(/^(\d+\. )(.*)/);
    return (
      <Text key={index} color={theme.white}>
        {"  "}
        {match ? match[1] : ""}
        {renderInlineSpans(match ? match[2] : line, theme.white)}
      </Text>
    );
  }
  // Empty line → blank spacer
  if (line.trim() === "") {
    return <Text key={index}>{" "}</Text>;
  }
  // Plain text
  return (
    <Text key={index} color={theme.white}>
      {renderInlineSpans(line, theme.white)}
    </Text>
  );
}

// ---------------------------------------------------------------------------
// Unified per-line renderer
// ---------------------------------------------------------------------------
function renderLine(line: string, index: number, kind: LineKind): React.ReactNode {
  if (kind === "fence") return renderFenceLine(line, index);
  if (kind === "code") return renderCodeLine(line, index);
  return renderMarkdownLine(line, index);
}

// ---------------------------------------------------------------------------
// Derive a short title from the first heading in the plan
// ---------------------------------------------------------------------------
function extractTitle(content: string): string {
  for (const line of content.split("\n")) {
    const stripped = line.replace(/^#+\s*/, "").trim();
    if (stripped) return stripped.slice(0, 50);
  }
  return "Plan";
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export function PlanModeOverlay({
  content,
  planPath,
  activePlanPath,
  onAccept,
  onRefine,
  onReject,
}: Props) {
  const { stdout } = useStdout();
  const terminalHeight = stdout?.rows ?? 24;
  const footerPathLineCount = activePlanPath ? 1 : 0;

  const lines = useMemo(() => content.split("\n"), [content]);
  const lineKinds = useMemo(() => computeLineKinds(lines), [lines]);

  // Reserve lines for: border top/bottom (2), header (1), separator (1), footer hint (1), footer actions (1), padding (2)
  const visibleLines = Math.max(4, terminalHeight - 10 - footerPathLineCount);

  const [scrollOffset, setScrollOffset] = useState(0);
  const [footerMode, setFooterMode] = useState<FooterMode>("idle");
  const [refineText, setRefineText] = useState("");

  // Keep the viewport "full" by clamping scroll to `lines.length - visibleLines`
  // (so the displayed slice length stays ~constant and doesn't visually shrink).
  //
  // Then compute `currentPage` based on the last visible line index, so when we
  // hit the final clamped offset (which may start earlier than an ideal
  // `n * visibleLines` boundary for partial pages) the indicator still shows
  // the correct last page (e.g. `7/7`).
  const totalPages = Math.max(1, Math.ceil(lines.length / visibleLines));
  const maxScroll = Math.max(0, lines.length - visibleLines);
  const currentPage = Math.min(
    totalPages,
    Math.floor((scrollOffset + visibleLines - 1) / visibleLines) + 1
  );

  const scroll = useCallback(
    (delta: number) => {
      setScrollOffset((prev) => Math.min(maxScroll, Math.max(0, prev + delta)));
    },
    [maxScroll]
  );

  useInput((input, key) => {
    if (footerMode === "refining") {
      if (key.escape) {
        setFooterMode("idle");
        setRefineText("");
      }
      // TextInput handles Enter internally via onSubmit
      return;
    }

    // Scrolling — arrows by line, PgUp/PgDn by window, g/G to extremes
    if (key.upArrow) scroll(-1);
    if (key.downArrow) scroll(1);
    if (key.pageUp) scroll(-visibleLines);
    if (key.pageDown) scroll(visibleLines);
    if (input === "g") setScrollOffset(0);
    if (input === "G") setScrollOffset(maxScroll);

    // Actions
    if (input.toLowerCase() === "a") {
      onAccept();
    }
    if (input.toLowerCase() === "r") {
      setFooterMode("refining");
      setRefineText("");
    }
    if (input.toLowerCase() === "x") {
      onReject();
    }
  });

  const handleRefineSubmit = useCallback(() => {
    const feedback = refineText.trim();
    setFooterMode("idle");
    setRefineText("");
    if (feedback) onRefine(feedback);
  }, [refineText, onRefine]);

  const displayedLines = lines.slice(scrollOffset, scrollOffset + visibleLines);
  const displayedKinds = lineKinds.slice(scrollOffset, scrollOffset + visibleLines);
  const title = extractTitle(content);
  const scrollIndicator = `[${currentPage}/${totalPages}]`;
  const activePlanPathDisplay =
    activePlanPath && activePlanPath.length > 70
      ? `...${activePlanPath.slice(-67)}`
      : activePlanPath;

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor={theme.purpleDim}
      paddingX={1}
      paddingY={0}
      flexShrink={0}
    >
      {/* Header */}
      <Box flexDirection="row" justifyContent="space-between" marginBottom={0}>
        <Text color={theme.purple} bold>
          {"◆ Plan  ·  "}
          <Text color={theme.lavender}>{title}</Text>
        </Text>
        <Text color={theme.mist} dimColor>
          {scrollIndicator}
        </Text>
      </Box>

      {/* Divider */}
      <Box marginBottom={0}>
        <Text color={theme.purpleDim}>{"─".repeat(60)}</Text>
      </Box>

      {/* Plan content */}
      <Box flexDirection="column" marginBottom={0}>
        {displayedLines.map((line, i) => (
          <Box key={scrollOffset + i}>
            {renderLine(line, scrollOffset + i, displayedKinds[i])}
          </Box>
        ))}
      </Box>

      {/* Divider */}
      <Box marginTop={0}>
        <Text color={theme.purpleDim}>{"─".repeat(60)}</Text>
      </Box>

      {/* Footer */}
      {footerMode === "refining" ? (
        <Box flexDirection="column" marginTop={0}>
          <Box marginBottom={0}>
            <Text color={theme.lavender}>Feedback</Text>
          </Box>
          <Box>
            <Text color={theme.purple} bold>
              {"› "}
            </Text>
            <TextInput
              key="refine-input"
              value={refineText}
              onChange={setRefineText}
              onSubmit={handleRefineSubmit}
              placeholder="Additional context or corrections…"
              showCursor
            />
          </Box>
          <Text color={theme.mist} dimColor>
            Enter — send feedback · Esc — back
          </Text>
        </Box>
      ) : (
        <Box flexDirection="column" marginTop={0}>
          <Text color={theme.mist} dimColor>
            ↑↓ line  PgUp/PgDn page  g/G top/bottom
          </Text>
          <Box
            flexDirection="row"
            justifyContent="space-between"
            alignItems="flex-end"
          >
            <Box gap={2}>
              <Text>
                <Text color={theme.mint} bold>
                  A
                </Text>
                <Text color={theme.white}> Accept</Text>
              </Text>
              <Text>
                <Text color={theme.lavender} bold>
                  R
                </Text>
                <Text color={theme.white}> Refine</Text>
              </Text>
              <Text>
                <Text color={theme.rose} bold>
                  X
                </Text>
                <Text color={theme.white}> Reject</Text>
              </Text>
            </Box>
            {activePlanPathDisplay ? (
              <Text color={theme.mist} dimColor>
                Plan path: {activePlanPathDisplay}
              </Text>
            ) : null}
          </Box>
        </Box>
      )}
    </Box>
  );
}
