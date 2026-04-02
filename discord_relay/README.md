# Proxi Discord Relay

This relay listens to Discord chat messages and forwards them to the Proxi gateway Discord webhook.

## Quick Start

1. Install dependencies:

```bash
cd discord_relay
bun install
```

2. Copy `.env.example` to `.env` and fill values.

The relay auto-loads env files at startup in this order:

1. Project root `.env` (global)
2. `discord_relay/.env` (fallback)

Existing shell env vars still take priority over file values.

3. Start Proxi gateway:

```bash
uv run proxi-gateway
```

4. Start relay:

```bash
bun run start
```

## Required Discord bot settings

- Enable `MESSAGE CONTENT INTENT` in the Discord Developer Portal.
- Invite bot to your server with permission to read/send channel messages.

## Notes

- By default, only messages prefixed with `/proxi` are forwarded.
- Set `PROXI_DISCORD_ALLOW_PLAIN=1` to forward all messages.
- Set `DISCORD_WEBHOOK_SECRET` in both relay and gateway env for HMAC verification.
