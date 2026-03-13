import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { createReadStream, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import { WebSocketServer } from "ws";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, "..");
const publicDir = path.join(__dirname, "public");
const port = Number(process.env.PORT || 5174);

function runPython(commandArgs) {
  return new Promise((resolve, reject) => {
    const child = spawn("uv", ["run", "--", "python", ...commandArgs], {
      cwd: projectRoot,
      env: process.env,
      shell: process.platform === "win32",
      stdio: ["ignore", "pipe", "pipe"],
    });

    let stdout = "";
    let stderr = "";

    child.stdout.setEncoding("utf-8");
    child.stderr.setEncoding("utf-8");

    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });

    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });

    child.on("error", (err) => {
      reject(err);
    });

    child.on("close", (code) => {
      if (code === 0) {
        resolve(stdout.trim());
        return;
      }
      reject(new Error(stderr.trim() || `Python command failed with exit code ${code}`));
    });
  });
}

async function initApiKeyDb() {
  await runPython(["-m", "proxi.security.key_store", "init"]);
}

async function listApiKeys() {
  const raw = await runPython(["-m", "proxi.security.key_store", "list"]);
  const payload = JSON.parse(raw || "{}");
  return payload.keys || [];
}

async function upsertApiKey(keyName, value) {
  const raw = await runPython([
    "-m",
    "proxi.security.key_store",
    "upsert",
    "--key",
    keyName,
    "--value",
    value,
  ]);
  return JSON.parse(raw || "{}");
}

async function listMcps() {
  const raw = await runPython(["-m", "proxi.security.key_store", "list-mcps"]);
  const payload = JSON.parse(raw || "{}");
  return payload.mcps || [];
}

async function toggleMcp(mcpName, enabled) {
  const command = enabled ? "enable-mcp" : "disable-mcp";
  const raw = await runPython(["-m", "proxi.security.key_store", command, mcpName]);
  return JSON.parse(raw || "{}");
}

async function loadEnvFromKeyStore() {
  const raw = await runPython(["-m", "proxi.security.key_store", "export-env"]);
  const payload = JSON.parse(raw || "{}");
  return payload.env || {};
}

async function readJsonBody(req) {
  const chunks = [];
  for await (const chunk of req) {
    chunks.push(chunk);
  }
  const text = Buffer.concat(chunks).toString("utf-8").trim();
  if (!text) return {};
  return JSON.parse(text);
}

function sendJson(res, statusCode, body) {
  res.statusCode = statusCode;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.end(JSON.stringify(body));
}

function contentType(filePath) {
  if (filePath.endsWith(".html")) return "text/html; charset=utf-8";
  if (filePath.endsWith(".css")) return "text/css; charset=utf-8";
  if (filePath.endsWith(".js")) return "application/javascript; charset=utf-8";
  return "text/plain; charset=utf-8";
}

const server = createServer(async (req, res) => {
  const method = req.method || "GET";
  const url = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);

  if (url.pathname === "/api/keys" && method === "GET") {
    try {
      const keys = await listApiKeys();
      sendJson(res, 200, { keys });
    } catch (error) {
      sendJson(res, 500, { error: String(error) });
    }
    return;
  }

  if (url.pathname.startsWith("/api/keys/") && method === "PUT") {
    try {
      const keyName = decodeURIComponent(url.pathname.replace("/api/keys/", "")).trim().toUpperCase();
      if (!keyName) {
        sendJson(res, 400, { error: "Key name is required" });
        return;
      }

      const body = await readJsonBody(req);
      const value = String(body?.value || "").trim();
      if (!value) {
        sendJson(res, 400, { error: "Key value is required" });
        return;
      }

      await upsertApiKey(keyName, value);
      sendJson(res, 200, { ok: true, keyName });
    } catch (error) {
      sendJson(res, 500, { error: String(error) });
    }
    return;
  }

  if (url.pathname === "/api/mcps" && method === "GET") {
    try {
      const mcps = await listMcps();
      sendJson(res, 200, { mcps });
    } catch (error) {
      sendJson(res, 500, { error: String(error) });
    }
    return;
  }

  if (url.pathname.startsWith("/api/mcps/") && method === "PUT") {
    try {
      const mcpName = decodeURIComponent(url.pathname.replace("/api/mcps/", "")).trim().toLowerCase();
      if (!mcpName) {
        sendJson(res, 400, { error: "MCP name is required" });
        return;
      }

      const body = await readJsonBody(req);
      const enabled = Boolean(body?.enabled);

      await toggleMcp(mcpName, enabled);
      sendJson(res, 200, { ok: true, mcpName, enabled });
    } catch (error) {
      sendJson(res, 500, { error: String(error) });
    }
    return;
  }

  const urlPath = req.url === "/" ? "/index.html" : req.url;
  const cleanPath = path.normalize(urlPath).replace(/^\.+/, "");
  const filePath = path.join(publicDir, cleanPath);

  if (!filePath.startsWith(publicDir) || !existsSync(filePath)) {
    res.statusCode = 404;
    res.end("Not Found");
    return;
  }

  res.setHeader("Content-Type", contentType(filePath));
  createReadStream(filePath).pipe(res);
});

const wss = new WebSocketServer({ server, path: "/bridge" });

wss.on("connection", (ws) => {
  let bridge = null;

  const startBridge = async () => {
    try {
      const keyEnv = await loadEnvFromKeyStore();
      const env = {
        ...process.env,
        ...keyEnv,
        PYTHONUNBUFFERED: "1",
        PYTHONPATH: `${projectRoot}${path.delimiter}${process.env.PYTHONPATH || ""}`,
      };

      bridge = spawn("uv", ["run", "proxi-bridge"], {
        cwd: projectRoot,
        env,
        shell: process.platform === "win32",
        stdio: ["pipe", "pipe", "pipe"],
      });

      bridge.stdout.setEncoding("utf-8");
      bridge.stderr.setEncoding("utf-8");

      bridge.stdout.on("data", (chunk) => {
        stdoutBuffer += chunk;
        const lines = stdoutBuffer.split("\n");
        stdoutBuffer = lines.pop() || "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) continue;
          if (ws.readyState === ws.OPEN) {
            ws.send(trimmed);
          }
        }
      });

      bridge.stderr.on("data", (chunk) => {
        const text = String(chunk).trim();
        if (!text || ws.readyState !== ws.OPEN) return;
        ws.send(JSON.stringify({ type: "bridge_stderr", content: text }));
      });

      bridge.on("exit", (code, signal) => {
        if (ws.readyState === ws.OPEN) {
          ws.send(JSON.stringify({ type: "bridge_exit", code, signal }));
          ws.close();
        }
      });
    } catch (error) {
      if (ws.readyState === ws.OPEN) {
        ws.send(
          JSON.stringify({
            type: "bridge_stderr",
            content: `Unable to start bridge: ${String(error)}`,
          })
        );
        ws.close();
      }
    }
  };

  let stdoutBuffer = "";

  startBridge();

  ws.on("message", (raw) => {
    const data = String(raw);
    if (!bridge || !bridge.stdin.writable) return;
    bridge.stdin.write(data.endsWith("\n") ? data : `${data}\n`);
  });

  ws.on("close", () => {
    if (bridge && bridge.exitCode == null) {
      bridge.kill();
    }
  });
});

initApiKeyDb()
  .then(() => {
    server.listen(port, () => {
      console.log(`Proxi React frontend running at http://localhost:${port}`);
    });
  })
  .catch((error) => {
    console.error(`Failed to initialize API key database: ${String(error)}`);
    process.exit(1);
  });
