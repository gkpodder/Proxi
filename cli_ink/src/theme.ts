/**
 * Proxi TUI colour palette.
 * All colours as hex for ANSI 256 / true colour usage.
 * Referenced throughout the spec by name.
 */
export const theme = {
  purple: "#C9B8FF",     // Primary accent — user messages, highlights, active selections
  purpleDim: "#8B7ACC",   // Secondary purple — borders, subtle chrome
  purpleFaint: "#2D2540", // Background tint for overlays and form containers
  lavender: "#E8DFFF",   // Agent response text
  mint: "#B8FFD9",       // Success states, completed tool calls
  peach: "#FFCBA8",      // Warnings, assumptions stated by agent
  rose: "#FFB8C6",       // Errors, destructive action confirmations
  mist: "#9BA8B8",       // Muted text — timestamps, hints, status
  white: "#F0EEFF",      // Primary text
  bg: "#14111E",         // Terminal background (informs overlay contrast)
} as const;
