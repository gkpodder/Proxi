/**
 * Boot sequence: Figlet title + animated status lines.
 * Rendered only once per session. Prints into scrollback buffer.
 */
import figlet from "figlet";
import chalk from "chalk";
import { printLine, colors } from "./scrollback.js";
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

/**
 * Renders the Proxi title using figlet (Big font) with a vertical gradient
 * from purple → purpleDim. Below it, a single dim tagline and version.
 * Call once at cold start, before any agent output.
 */
export function printFigletTitle(): void {
  const data = figlet.textSync("Proxi", { font: "Big" });
  const lines = data.split("\n").filter((l) => l.length > 0);
  const purpleRgb = hexToRgb(theme.purple);
  const purpleDimRgb = hexToRgb(theme.purpleDim);
  const n = lines.length;

  for (let i = 0; i < n; i++) {
    const t = n <= 1 ? 0 : i / (n - 1);
    const [r, g, b] = lerpRgb(purpleRgb, purpleDimRgb, t);
    const lineColor = chalk.hex(rgbToHex(r, g, b));
    printLine(`  ${lineColor(lines[i] ?? "")}`);
  }

  printLine("");
  printLine(`  ${colors.mist("your computer, in plain language")}       ${colors.mist(`v${VERSION}`)}`);
  printLine("");
}
