/**
 * Proxi Figlet title with vertical gradient (purple → purpleDim).
 * Rendered as Ink component so it stays visible until conversation scrolls it.
 */
import React from "react";
import { Box, Text } from "ink";
import figlet from "figlet";
import { theme } from "../theme.js";

const VERSION = "0.1.0";

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff];
}

function rgbToHex(r: number, g: number, b: number): string {
  return "#" + [r, g, b].map((x) => Math.round(x).toString(16).padStart(2, "0")).join("");
}

function lerpRgb(
  a: [number, number, number],
  b: [number, number, number],
  t: number
): [number, number, number] {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
}

/** Number of lines the title occupies (figlet + tagline) for scroll calculations */
export const FIGLET_LINE_COUNT = (() => {
  const data = figlet.textSync("Proxi", { font: "Big" });
  return data.split("\n").filter((l) => l.length > 0).length + 1; // +1 for tagline
})();

type Props = {
  /** Render only lines from this index (inclusive) */
  startLine?: number;
  /** Max number of lines to render (default: all) */
  maxLines?: number;
};

export function FigletTitle({ startLine = 0, maxLines }: Props) {
  const data = figlet.textSync("Proxi", { font: "Big" });
  const lines = data.split("\n").filter((l) => l.length > 0);
  const purpleRgb = hexToRgb(theme.purple);
  const purpleDimRgb = hexToRgb(theme.purpleDim);
  const n = lines.length;
  const endLine = maxLines != null ? Math.min(startLine + maxLines, n + 1) : n + 1;

  const elements: React.ReactNode[] = [];
  for (let i = startLine; i < endLine; i++) {
    if (i < n) {
      const t = n <= 1 ? 0 : i / (n - 1);
      const [r, g, b] = lerpRgb(purpleRgb, purpleDimRgb, t);
      const hex = rgbToHex(r, g, b);
      elements.push(
        <Text key={i} color={hex}>
          {"  "}
          {lines[i]}
        </Text>
      );
    } else {
      elements.push(
        <Box key="tagline">
          <Text dimColor>{"  your computer, in plain language       "}</Text>
          <Text dimColor>{`v${VERSION}`}</Text>
        </Box>
      );
    }
  }

  return <Box flexDirection="column">{elements}</Box>;
}
