import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, "..");
const gatewayBaseUrl = (process.env.PROXI_GATEWAY_URL || `http://127.0.0.1:${process.env.GATEWAY_PORT || 8765}`).replace(/\/$/, "");

let relayProcess = null;
let cleanupStarted = false;

function withTimeout(promise, ms, fallbackValue = null) {
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(fallbackValue), ms);
    promise
      .then((value) => {
        clearTimeout(timer);
        resolve(value);
      })
      .catch(() => {
        clearTimeout(timer);
        resolve(fallbackValue);
      });
  });
}

async function detectGateway() {
  const response = await withTimeout(fetch(`${gatewayBaseUrl}/health`), 1200, null);
  return Boolean(response && response.ok);
}

async function ensureGatewayReady() {
  if (await detectGateway()) return;
  throw new Error(`Gateway is not reachable at ${gatewayBaseUrl}. Start it first.`);
}

function cleanupGateway() {
  if (cleanupStarted) return;
  cleanupStarted = true;

  if (relayProcess && relayProcess.exitCode == null) {
    relayProcess.kill();
  }
}

function attachShutdownHooks() {
  const shutdown = () => cleanupGateway();

  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
  process.on("exit", shutdown);
}

async function main() {
  await ensureGatewayReady();
  attachShutdownHooks();

  relayProcess = spawn("bun", ["run", "start"], {
    cwd: path.join(projectRoot, "discord_relay"),
    env: process.env,
    shell: process.platform === "win32",
    stdio: "inherit",
  });

  relayProcess.on("exit", (code) => {
    cleanupGateway();
    process.exit(code ?? 0);
  });
}

main().catch((error) => {
  console.error(`[relay-launcher] ${String(error?.message || error)}`);
  cleanupGateway();
  process.exit(1);
});
