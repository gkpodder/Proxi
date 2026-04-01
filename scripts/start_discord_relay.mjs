import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, "..");
const gatewayBaseUrl = (process.env.PROXI_GATEWAY_URL || `http://127.0.0.1:${process.env.GATEWAY_PORT || 8765}`).replace(/\/$/, "");
const argv = new Set(process.argv.slice(2));
const disableGatewayAutostart =
  argv.has("--use-existing-gateway") ||
  argv.has("--no-gateway-start") ||
  String(process.env.PROXI_GATEWAY_AUTOSTART || "1").trim().toLowerCase() === "0";

let managedGatewayProcess = null;
let relayProcess = null;

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

function startManagedGateway() {
  if (managedGatewayProcess && managedGatewayProcess.exitCode == null) {
    return managedGatewayProcess;
  }

  managedGatewayProcess = spawn("uv", ["run", "proxi-gateway"], {
    cwd: projectRoot,
    env: process.env,
    shell: process.platform === "win32",
    stdio: ["ignore", "ignore", "pipe"],
  });

  managedGatewayProcess.stderr.setEncoding("utf-8");
  managedGatewayProcess.stderr.on("data", (chunk) => {
    const text = String(chunk || "").trim();
    if (text) {
      console.error(`[gateway] ${text}`);
    }
  });

  managedGatewayProcess.on("exit", (code) => {
    if (relayProcess && relayProcess.exitCode == null) {
      console.error(`[gateway] exited with code ${code ?? "null"}`);
    }
  });

  return managedGatewayProcess;
}

async function ensureGatewayReady() {
  if (await detectGateway()) return;

  if (disableGatewayAutostart) {
    throw new Error(
      `Gateway is not reachable at ${gatewayBaseUrl}. Start it first, or run without --use-existing-gateway.`
    );
  }

  console.log(`[relay-launcher] Gateway not detected at ${gatewayBaseUrl}; starting managed gateway...`);
  startManagedGateway();

  const maxAttempts = 30;
  for (let i = 0; i < maxAttempts; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 300));
    if (await detectGateway()) {
      console.log("[relay-launcher] Gateway is ready.");
      return;
    }
  }

  throw new Error(`Gateway did not become ready at ${gatewayBaseUrl}`);
}

function stopManagedGateway() {
  if (!managedGatewayProcess || managedGatewayProcess.exitCode != null) return;
  managedGatewayProcess.kill();
}

function attachShutdownHooks() {
  const shutdown = () => {
    if (relayProcess && relayProcess.exitCode == null) {
      relayProcess.kill();
    }
    stopManagedGateway();
  };

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
    stopManagedGateway();
    process.exit(code ?? 0);
  });
}

main().catch((error) => {
  console.error(`[relay-launcher] ${String(error?.message || error)}`);
  process.exit(1);
});
