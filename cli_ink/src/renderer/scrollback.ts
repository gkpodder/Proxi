/**
 * ANSI print functions for Zone A (scrollback) output.
 * Writes directly to process.stdout. Preserves native terminal scroll,
 * Cmd+F search, and text selection.
 */
import chalk from "chalk";
import { theme } from "../theme.js";

const hex = (h: string) => chalk.hex(h);

export function printLine(text: string): void {
  process.stdout.write(text + "\n");
}

export function printRaw(text: string): void {
  process.stdout.write(text);
}

export function clearLine(): void {
  process.stdout.write("\r\x1b[K");
}

export const colors = {
  purple: hex(theme.purple),
  purpleDim: hex(theme.purpleDim),
  purpleFaint: hex(theme.purpleFaint),
  lavender: hex(theme.lavender),
  mint: hex(theme.mint),
  peach: hex(theme.peach),
  rose: hex(theme.rose),
  mist: hex(theme.mist),
  white: hex(theme.white),
  bold: chalk.bold,
} as const;
