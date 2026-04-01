import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createInterface } from "node:readline/promises";
import { stdin as input, stdout as output } from "node:process";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, "..");
const gatewayBaseUrl = (process.env.PROXI_GATEWAY_URL || `http://127.0.0.1:${process.env.GATEWAY_PORT || 8765}`).replace(/\/$/, "");

let managedGatewayProcess = null;
let managedGatewayStarted = false;
let activeChild = null;
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

function gatewayCommand() {
  const pythonCandidates = process.platform === "win32"
    ? [path.join(projectRoot, ".venv", "Scripts", "python.exe")]
    : [path.join(projectRoot, ".venv", "bin", "python")];

  for (const pythonPath of pythonCandidates) {
    if (pythonPath && existsSync(pythonPath)) {
      return { command: pythonPath, args: ["-m", "proxi.gateway.daemon_cli", "start"] };
    }
  }

  return { command: "uv", args: ["run", "proxi-gateway-ctl", "start"] };
}

function gatewayStopCommand() {
  const pythonCandidates = process.platform === "win32"
    ? [path.join(projectRoot, ".venv", "Scripts", "python.exe")]
    : [path.join(projectRoot, ".venv", "bin", "python")];

  for (const pythonPath of pythonCandidates) {
    if (pythonPath && existsSync(pythonPath)) {
      return { command: pythonPath, args: ["-m", "proxi.gateway.daemon_cli", "stop"] };
    }
  }

  return { command: "uv", args: ["run", "proxi-gateway-ctl", "stop"] };
}

async function detectGateway() {
  const response = await withTimeout(fetch(`${gatewayBaseUrl}/health`), 1200, null);
  return Boolean(response && response.ok);
}

function startManagedGateway() {
  if (managedGatewayProcess && managedGatewayProcess.exitCode == null) {
    return managedGatewayProcess;
  }

  const gateway = gatewayCommand();
  managedGatewayStarted = true;
  managedGatewayProcess = spawn(gateway.command, gateway.args, {
    cwd: projectRoot,
    env: process.env,
    shell: gateway.command === "uv" && process.platform === "win32",
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
    if (code && code !== 0) {
      console.error(`[gateway] exited with code ${code}`);
    }
  });

  return managedGatewayProcess;
}

async function ensureGatewayReady() {
  if (await detectGateway()) return false;

  console.log(`Gateway not detected at ${gatewayBaseUrl}; starting managed gateway...`);
  startManagedGateway();

  const maxAttempts = 60;
  for (let i = 0; i < maxAttempts; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 500));
    if (await detectGateway()) {
      console.log("Gateway is ready.");
      return true;
    }
  }

  throw new Error(`Gateway did not become ready at ${gatewayBaseUrl}`);
}

function stopManagedGateway() {
  if (!managedGatewayProcess || managedGatewayProcess.exitCode != null) return;
  managedGatewayProcess.kill();
}

function stopGatewayDaemon() {
  if (!managedGatewayStarted) return;
  const gateway = gatewayStopCommand();
  spawnSync(gateway.command, gateway.args, {
    cwd: projectRoot,
    env: process.env,
    shell: gateway.command === "uv" && process.platform === "win32",
    stdio: "ignore",
  });
}

function cleanupGateway() {
  if (cleanupStarted) return;
  cleanupStarted = true;

  if (activeChild && activeChild.exitCode == null) {
    activeChild.kill();
  }

  stopGatewayDaemon();
  stopManagedGateway();
}

function attachShutdownHooks() {
  const shutdown = () => cleanupGateway();

  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
  process.on("exit", shutdown);
}

function runCommand(command, args, options = {}) {
  return new Promise((resolve) => {
    const child = spawn(command, args, {
      cwd: options.cwd || projectRoot,
      env: options.env || process.env,
      shell: process.platform === "win32",
      stdio: options.stdio || "inherit",
    });

    activeChild = child;
    child.on("exit", (code) => {
      if (activeChild === child) {
        activeChild = null;
      }
      resolve(code ?? 0);
    });
  });
}

async function askChoice() {
  const gatewayRunning = await detectGateway();
  console.log("\nProxi Launcher");
  console.log(`Gateway: ${gatewayRunning ? "running" : "not running"} (${gatewayBaseUrl})`);
  console.log("1) TUI");
  console.log("2) React");
  console.log("3) Discord Relay");
  console.log("4) Headless");

  const rl = createInterface({ input, output });
  try {
    const choice = (await rl.question("Choose mode [1-4]: ")).trim();
    return choice;
  } finally {
    rl.close();
  }
}

async function runHeadless() {
  const rl = createInterface({ input, output });
  try {
    const task = (await rl.question("Enter headless task: ")).trim();
    if (!task) {
      console.error("Task is required.");
      return 1;
    }
    return await runCommand("uv", ["run", "proxi-run", task]);
  } finally {
    rl.close();
  }
}

async function main() {
  attachShutdownHooks();
  const choice = await askChoice();

  if (choice === "1") {
    await ensureGatewayReady();
    const code = await runCommand("bun", ["run", "proxi-tui"]);
    cleanupGateway();
    process.exit(code);
  }

  if (choice === "2") {
    await ensureGatewayReady();
    const code = await runCommand("bun", ["run", "proxi-react:existing-gateway"]);
    cleanupGateway();
    process.exit(code);
  }

  if (choice === "3") {
    await ensureGatewayReady();
    const code = await runCommand("bun", ["run", "proxi-discord-relay:existing-gateway"]);
    cleanupGateway();
    process.exit(code);
  }

  if (choice === "4") {
    const code = await runHeadless();
    cleanupGateway();
    process.exit(code);
  }

  console.error("Invalid choice. Use 1, 2, 3, or 4.");
  cleanupGateway();
  process.exit(1);
}

main().catch((error) => {
  console.error(String(error?.message || error));
  cleanupGateway();
  process.exit(1);
});
