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

function contentType(filePath) {
  if (filePath.endsWith(".html")) return "text/html; charset=utf-8";
  if (filePath.endsWith(".css")) return "text/css; charset=utf-8";
  if (filePath.endsWith(".js")) return "application/javascript; charset=utf-8";
  return "text/plain; charset=utf-8";
}

const server = createServer(async (req, res) => {
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
  const env = {
    ...process.env,
    PYTHONUNBUFFERED: "1",
    PYTHONPATH: `${projectRoot}${path.delimiter}${process.env.PYTHONPATH || ""}`,
  };

  const bridge = spawn("uv", ["run", "proxi-bridge"], {
    cwd: projectRoot,
    env,
    shell: process.platform === "win32",
    stdio: ["pipe", "pipe", "pipe"],
  });

  let stdoutBuffer = "";

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

  ws.on("message", (raw) => {
    const data = String(raw);
    if (!bridge.stdin.writable) return;
    bridge.stdin.write(data.endsWith("\n") ? data : `${data}\n`);
  });

  ws.on("close", () => {
    if (bridge.exitCode == null) {
      bridge.kill();
    }
  });
});

server.listen(port, () => {
  console.log(`Proxi React frontend running at http://localhost:${port}`);
});
