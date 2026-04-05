import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import { Client, GatewayIntentBits, Partials } from "discord.js";

function loadDotEnvIfPresent() {
  const __filename = fileURLToPath(import.meta.url);
  const __dirname = path.dirname(__filename);
  const envPaths = [
    // Global project env file (repo root)
    path.resolve(__dirname, "..", "..", ".env"),
    // Local relay-specific env file (optional fallback)
    path.resolve(__dirname, "..", ".env"),
  ];

  for (const envPath of envPaths) {
    if (!fs.existsSync(envPath)) continue;

    const text = fs.readFileSync(envPath, "utf-8");
    for (const rawLine of text.split(/\r?\n/)) {
      const line = rawLine.trim();
      if (!line || line.startsWith("#")) continue;
      const idx = line.indexOf("=");
      if (idx <= 0) continue;
      const key = line.slice(0, idx).trim();
      if (!key || process.env[key]) continue;
      let value = line.slice(idx + 1).trim();
      if (
        (value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))
      ) {
        value = value.slice(1, -1);
      }
      process.env[key] = value;
    }
  }
}

loadDotEnvIfPresent();

const BOT_TOKEN = String(process.env.DISCORD_BOT_TOKEN || "").trim();
const WEBHOOK_URL = String(
  process.env.PROXI_DISCORD_WEBHOOK_URL || "http://127.0.0.1:8765/channels/discord/webhook"
).trim();
const WEBHOOK_SECRET = String(process.env.DISCORD_WEBHOOK_SECRET || "").trim();
const COMMAND_PREFIX = String(process.env.PROXI_DISCORD_COMMAND_PREFIX || "/proxi").trim() || "/proxi";
const FORWARD_PLAIN = ["1", "true", "yes"].includes(
  String(process.env.PROXI_DISCORD_ALLOW_PLAIN || "0").trim().toLowerCase()
);

const ALLOWED_CHANNELS = new Set(
  String(process.env.PROXI_DISCORD_ALLOWED_CHANNEL_IDS || "")
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean)
);
const ALLOWED_USERS = new Set(
  String(process.env.PROXI_DISCORD_ALLOWED_USER_IDS || "")
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean)
);

if (!BOT_TOKEN) {
  throw new Error("DISCORD_BOT_TOKEN is required");
}

function shouldForwardMessage(message) {
  if (!message?.content || message.author?.bot) return false;

  if (ALLOWED_CHANNELS.size > 0 && !ALLOWED_CHANNELS.has(String(message.channelId || ""))) {
    return false;
  }

  if (ALLOWED_USERS.size > 0 && !ALLOWED_USERS.has(String(message.author?.id || ""))) {
    return false;
  }

  if (FORWARD_PLAIN) return true;
  return String(message.content).trim().startsWith(COMMAND_PREFIX);
}

function signedHeaders(body) {
  const headers = { "Content-Type": "application/json" };
  if (!WEBHOOK_SECRET) return headers;

  const sig = crypto.createHmac("sha256", WEBHOOK_SECRET).update(body).digest("hex");
  headers["X-Signature-256"] = `sha256=${sig}`;
  return headers;
}

async function forwardToGateway(message) {
  const payload = {
    content: String(message.content || ""),
    channel_id: String(message.channelId || ""),
    guild_id: String(message.guildId || ""),
    message_id: String(message.id || ""),
    author: {
      id: String(message.author?.id || ""),
      username: String(message.author?.username || ""),
      bot: Boolean(message.author?.bot),
    },
    timestamp: message.createdAt ? message.createdAt.toISOString() : new Date().toISOString(),
  };

  const body = JSON.stringify(payload);
  const response = await fetch(WEBHOOK_URL, {
    method: "POST",
    headers: signedHeaders(body),
    body,
  });

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(`Gateway returned ${response.status}: ${text}`);
  }
}

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.DirectMessages,
    GatewayIntentBits.MessageContent,
  ],
  partials: [Partials.Channel],
});

client.once("clientReady", () => {
  // eslint-disable-next-line no-console
  console.log(`Discord relay connected as ${client.user?.tag || "unknown"}`);
});

client.on("messageCreate", async (message) => {
  try {
    if (!shouldForwardMessage(message)) return;
    await forwardToGateway(message);
  } catch (error) {
    // eslint-disable-next-line no-console
    console.error("Failed to forward Discord message:", error);
    try {
      await message.reply("Proxi relay could not deliver your command. Check gateway/relay logs.");
    } catch {
      // ignore
    }
  }
});

// Derive gateway base URL from WEBHOOK_URL (strip path after host)
const GATEWAY_BASE_URL = (() => {
  try {
    const u = new URL(WEBHOOK_URL);
    return `${u.protocol}//${u.host}`;
  } catch {
    return "http://127.0.0.1:8765";
  }
})();

async function deregisterFromGateway() {
  try {
    const body = "";
    await fetch(`${GATEWAY_BASE_URL}/channels/discord/deregister`, {
      method: "POST",
      headers: signedHeaders(body),
      body,
    });
    // eslint-disable-next-line no-console
    console.log("Discord relay deregistered from gateway.");
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error("Failed to deregister from gateway:", err);
  }
}

async function shutdown() {
  await deregisterFromGateway();
  await client.destroy();
  process.exit(0);
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

client.login(BOT_TOKEN);
