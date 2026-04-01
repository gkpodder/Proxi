import { createServer } from "node:http";
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
const gatewayBaseUrl = (process.env.PROXI_GATEWAY_URL || `http://127.0.0.1:${process.env.GATEWAY_PORT || 8765}`).replace(/\/$/, "");
const preferredSessionId = process.env.PROXI_SESSION_ID || "";

let gatewayEnabled = false;

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
  const force = String(process.env.PROXI_TRANSPORT || "").trim().toLowerCase();
  if (force && force !== "gateway") {
    throw new Error("Only gateway transport is supported. Set PROXI_TRANSPORT=gateway or unset it.");
  }

  const response = await withTimeout(fetch(`${gatewayBaseUrl}/health`), 1200, null);
  return Boolean(response && response.ok);
}

async function ensureGatewayReady() {
  if (await detectGateway()) return;
  throw new Error(`Gateway is not reachable at ${gatewayBaseUrl}. Start it first.`);
}

async function gatewayGet(pathname) {
  const response = await fetch(`${gatewayBaseUrl}${pathname}`);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload?.detail || payload?.error || `Gateway request failed: ${response.status}`);
  }
  return payload;
}

async function gatewayPost(pathname, body = {}) {
  const response = await fetch(`${gatewayBaseUrl}${pathname}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload?.detail || payload?.error || `Gateway request failed: ${response.status}`);
  }
  return payload;
}

async function gatewayPut(pathname, body = {}) {
  const response = await fetch(`${gatewayBaseUrl}${pathname}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload?.detail || payload?.error || `Gateway request failed: ${response.status}`);
  }
  return payload;
}

async function gatewayDelete(pathname) {
  const response = await fetch(`${gatewayBaseUrl}${pathname}`, {
    method: "DELETE",
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload?.detail || payload?.error || `Gateway request failed: ${response.status}`);
  }
  return payload;
}

async function resolveInitialSessionId() {
  if (preferredSessionId) return preferredSessionId;

  const agentsPayload = await gatewayGet("/v1/agents");
  const agents = Array.isArray(agentsPayload?.agents) ? agentsPayload.agents : [];
  if (agents.length === 0) {
    throw new Error("No agents are configured in gateway.");
  }

  const primary = agents[0];
  const agentId = String(primary?.agent_id || "").trim();
  const sessionName = String(primary?.default_session || "main").trim() || "main";
  if (!agentId) {
    throw new Error("Gateway returned an invalid agent configuration.");
  }
  return `${agentId}/${sessionName}`;
}

function parseSseChunk(buffer, onData) {
  let cursor = buffer;
  while (true) {
    const boundary = cursor.indexOf("\n\n");
    if (boundary < 0) break;
    const rawEvent = cursor.slice(0, boundary);
    cursor = cursor.slice(boundary + 2);

    const dataLines = rawEvent
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart());

    if (dataLines.length > 0) {
      onData(dataLines.join("\n"));
    }
  }
  return cursor;
}

function createGatewaySessionController(ws) {
  let closed = false;
  let streamAbort = null;
  let activeSessionId = null;
  let pendingSwitchPrompt = false;
  let streamGeneration = 0;

  const sendToClient = (payload) => {
    if (closed || ws.readyState !== ws.OPEN) return;
    ws.send(typeof payload === "string" ? payload : JSON.stringify(payload));
  };

  const closeStream = () => {
    if (streamAbort) {
      streamAbort.abort();
      streamAbort = null;
    }
  };

  const attachStream = async (sessionId) => {
    closeStream();
    activeSessionId = sessionId;

    const generation = ++streamGeneration;
    const controller = new AbortController();
    streamAbort = controller;

    try {
      const response = await fetch(
        `${gatewayBaseUrl}/v1/sessions/${encodeURIComponent(sessionId)}/stream`,
        { signal: controller.signal }
      );

      if (!response.ok || !response.body) {
        throw new Error(`Unable to open stream for session ${sessionId}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let sseBuffer = "";

      while (!closed && generation === streamGeneration) {
        const { done, value } = await reader.read();
        if (done) break;
        sseBuffer += decoder.decode(value, { stream: true });
        sseBuffer = parseSseChunk(sseBuffer, (eventData) => {
          if (!eventData || eventData.startsWith(":")) return;
          sendToClient(eventData);
        });
      }
    } catch (error) {
      const isAbort =
        error?.name === "AbortError" ||
        (typeof error?.message === "string" && /aborted/i.test(error.message));
      if (isAbort || closed || generation !== streamGeneration) {
        return;
      }
      throw error;
    } finally {
      if (streamAbort === controller) {
        streamAbort = null;
      }
    }
  };

  const startStream = (sessionId) => {
    attachStream(sessionId).catch((error) => {
      sendToClient({
        type: "bridge_stderr",
        content: `Gateway stream error: ${String(error)}`,
      });
    });
  };

  const start = async () => {
    const initialSession = await resolveInitialSessionId();
    startStream(initialSession);
  };

  const switchToAgent = async (agentId) => {
    const targetAgentId = String(agentId || "").trim();
    if (!targetAgentId) {
      throw new Error("agentId is required for switch_agent_to");
    }

    const switched = await gatewayPost("/v1/sessions/switch", { agent_id: targetAgentId });
    const nextSession = String(switched?.session_id || "").trim();
    if (!nextSession) throw new Error("Gateway switch response did not include session_id.");
    sendToClient({ type: "status_update", label: "Switching agent...", status: "running" });
    startStream(nextSession);
    sendToClient({ type: "status_update", label: "Agent switch complete", status: "done" });
  };

  const onMessage = async (data) => {
    let message;
    try {
      message = JSON.parse(String(data));
    } catch {
      return;
    }

    const msgType = message?.type;
    if (!msgType) return;

    if (msgType === "start") {
      const task = String(message.task || "").trim();
      if (!task || !activeSessionId) return;
      await gatewayPost(`/v1/sessions/${encodeURIComponent(activeSessionId)}/send`, { message: task });
      return;
    }

    if (msgType === "abort") {
      if (!activeSessionId) return;
      await gatewayPost(`/v1/sessions/${encodeURIComponent(activeSessionId)}/abort`, {});
      return;
    }

    if (msgType === "user_input_response") {
      const payload = message?.payload;
      if (!payload || !activeSessionId) return;
      await gatewayPost(`/v1/sessions/${encodeURIComponent(activeSessionId)}/send`, {
        message: "form answer",
        form_answer: payload,
      });
      return;
    }

    if (msgType === "switch_agent") {
      const agentsPayload = await gatewayGet("/v1/agents");
      const agents = Array.isArray(agentsPayload?.agents) ? agentsPayload.agents : [];
      const options = agents.map((a) => String(a.agent_id || "").trim()).filter(Boolean);
      if (options.length === 0) {
        sendToClient({ type: "bridge_stderr", content: "No agents available to switch." });
        return;
      }
      pendingSwitchPrompt = true;
      sendToClient({
        type: "user_input_required",
        method: "select",
        prompt: "Select an agent",
        options,
      });
      return;
    }

    if (msgType === "switch_agent_to") {
      pendingSwitchPrompt = false;
      await switchToAgent(message?.agentId);
      return;
    }

    if (msgType === "user_input") {
      const value = String(message?.value || "").trim();
      if (!value || !activeSessionId) return;

      if (pendingSwitchPrompt) {
        pendingSwitchPrompt = false;
        await switchToAgent(value);
        return;
      }

      await gatewayPost(`/v1/sessions/${encodeURIComponent(activeSessionId)}/send`, {
        message: value,
      });
    }
  };

  const onClose = () => {
    closed = true;
    closeStream();
  };

  return { start, onMessage, onClose };
}

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
  if (gatewayEnabled) {
    const payload = await gatewayGet("/v1/mcps");
    const mcps = Array.isArray(payload?.mcps) ? payload.mcps : [];
    return mcps.map((item) => ({
      mcp_name: String(item?.name || ""),
      enabled: Boolean(item?.enabled),
    }));
  }

  const raw = await runPython(["-m", "proxi.security.key_store", "list-mcps"]);
  const payload = JSON.parse(raw || "{}");
  return payload.mcps || [];
}

async function toggleMcp(mcpName, enabled) {
  if (gatewayEnabled) {
    const currentMcps = await listMcps();
    const current = currentMcps.find((entry) => entry.mcp_name === mcpName);
    const currentEnabled = Boolean(current?.enabled);
    if (currentEnabled !== enabled) {
      await gatewayPost(`/v1/mcps/${encodeURIComponent(mcpName)}/toggle`, {});
    }
    return { ok: true, mcp_name: mcpName, enabled };
  }

  const command = enabled ? "enable-mcp" : "disable-mcp";
  const raw = await runPython(["-m", "proxi.security.key_store", command, mcpName]);
  return JSON.parse(raw || "{}");
}

async function getUserProfile() {
  const raw = await runPython(["-m", "proxi.security.key_store", "get-profile"]);
  const payload = JSON.parse(raw || "{}");
  return {
    profile: payload.profile || null,
    updatedAt: payload.updated_at || null,
  };
}

async function listCronJobs() {
  const payload = await gatewayGet("/v1/cron-jobs");
  return Array.isArray(payload?.cron_jobs) ? payload.cron_jobs : [];
}

async function listAgents() {
  const payload = await gatewayGet("/v1/agents");
  const agents = Array.isArray(payload?.agents) ? payload.agents : [];
  return agents
    .map((item) => String(item?.agent_id || "").trim())
    .filter(Boolean);
}

async function getLlmConfig() {
  const payload = await gatewayGet("/v1/llm-config");
  return {
    provider: String(payload?.provider || "openai").trim().toLowerCase(),
    model: String(payload?.model || "").trim(),
    providers: Array.isArray(payload?.providers) ? payload.providers : [],
    models: payload?.models && typeof payload.models === "object" ? payload.models : {},
    defaults: payload?.defaults && typeof payload.defaults === "object" ? payload.defaults : {},
  };
}

async function updateLlmConfig(provider, model) {
  const payload = await gatewayPut("/v1/llm-config", {
    provider: String(provider || "").trim().toLowerCase(),
    model: String(model || "").trim(),
  });
  return {
    provider: String(payload?.provider || "openai").trim().toLowerCase(),
    model: String(payload?.model || "").trim(),
    providers: Array.isArray(payload?.providers) ? payload.providers : [],
    models: payload?.models && typeof payload.models === "object" ? payload.models : {},
    defaults: payload?.defaults && typeof payload.defaults === "object" ? payload.defaults : {},
  };
}

async function getCronCapabilities() {
  try {
    const payload = await gatewayGet("/v1/cron-capabilities");
    return {
      supportsSixField: Boolean(payload?.supports_six_field),
    };
  } catch {
    return {
      supportsSixField: false,
    };
  }
}

async function upsertCronJob(sourceId, cronJob) {
  return gatewayPut(`/v1/cron-jobs/${encodeURIComponent(sourceId)}`, cronJob);
}

async function deleteCronJob(sourceId) {
  return gatewayDelete(`/v1/cron-jobs/${encodeURIComponent(sourceId)}`);
}

async function setCronPaused(sourceId, paused) {
  return gatewayPost(`/v1/cron-jobs/${encodeURIComponent(sourceId)}/pause`, {
    paused: Boolean(paused),
  });
}

async function listWebhooks() {
  const payload = await gatewayGet("/v1/webhooks");
  return Array.isArray(payload?.webhooks) ? payload.webhooks : [];
}

async function upsertWebhook(sourceId, webhook) {
  return gatewayPut(`/v1/webhooks/${encodeURIComponent(sourceId)}`, webhook);
}

async function deleteWebhook(sourceId) {
  return gatewayDelete(`/v1/webhooks/${encodeURIComponent(sourceId)}`);
}

async function setWebhookPaused(sourceId, paused) {
  return gatewayPost(`/v1/webhooks/${encodeURIComponent(sourceId)}/pause`, {
    paused: Boolean(paused),
  });
}

async function upsertUserProfile(profile) {
  const encoded = Buffer.from(JSON.stringify(profile || {}), "utf-8").toString("base64");
  const raw = await runPython([
    "-m",
    "proxi.security.key_store",
    "upsert-profile",
    "--json-base64",
    encoded,
  ]);
  return JSON.parse(raw || "{}");
}

async function deleteUserProfile() {
  const raw = await runPython(["-m", "proxi.security.key_store", "delete-profile"]);
  return JSON.parse(raw || "{}");
}

async function readJsonBody(req) {
  const chunks = [];
  for await (const chunk of req) {
    chunks.push(chunk);
  }
  const text = Buffer.concat(chunks).toString("utf-8").trim();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    const err = new Error("Invalid JSON in request body");
    err.statusCode = 400;
    throw err;
  }
}

function sendError(res, error) {
  const status = error?.statusCode ?? 500;
  sendJson(res, status, { error: String(error) });
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
      sendError(res, error);
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
      sendError(res, error);
    }
    return;
  }

  if (url.pathname === "/api/mcps" && method === "GET") {
    try {
      const mcps = await listMcps();
      sendJson(res, 200, { mcps });
    } catch (error) {
      sendError(res, error);
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
      sendError(res, error);
    }
    return;
  }

  if (url.pathname === "/api/profile" && method === "GET") {
    try {
      const { profile, updatedAt } = await getUserProfile();
      sendJson(res, 200, { profile, updatedAt });
    } catch (error) {
      sendError(res, error);
    }
    return;
  }

  if (url.pathname === "/api/profile" && method === "PUT") {
    try {
      const body = await readJsonBody(req);
      const profile = body?.profile;
      if (!profile || typeof profile !== "object" || Array.isArray(profile)) {
        sendJson(res, 400, { error: "Profile must be a JSON object" });
        return;
      }

      await upsertUserProfile(profile);
      sendJson(res, 200, { ok: true });
    } catch (error) {
      sendError(res, error);
    }
    return;
  }

  if (url.pathname === "/api/profile" && method === "DELETE") {
    try {
      await deleteUserProfile();
      sendJson(res, 200, { ok: true });
    } catch (error) {
      sendError(res, error);
    }
    return;
  }

  if (url.pathname === "/api/cron-jobs" && method === "GET") {
    try {
      const cronJobs = await listCronJobs();
      sendJson(res, 200, { cronJobs });
    } catch (error) {
      sendError(res, error);
    }
    return;
  }

  if (url.pathname === "/api/agents" && method === "GET") {
    try {
      const agents = await listAgents();
      sendJson(res, 200, { agents });
    } catch (error) {
      sendError(res, error);
    }
    return;
  }

  if (url.pathname === "/api/llm-config" && method === "GET") {
    try {
      const config = await getLlmConfig();
      sendJson(res, 200, config);
    } catch (error) {
      sendError(res, error);
    }
    return;
  }

  if (url.pathname === "/api/llm-config" && method === "PUT") {
    try {
      const body = await readJsonBody(req);
      const provider = String(body?.provider || "").trim().toLowerCase();
      const model = String(body?.model || "").trim();
      if (!provider) {
        sendJson(res, 400, { error: "provider is required" });
        return;
      }

      const config = await updateLlmConfig(provider, model);
      sendJson(res, 200, config);
    } catch (error) {
      sendError(res, error);
    }
    return;
  }

  if (url.pathname === "/api/cron-capabilities" && method === "GET") {
    try {
      const capabilities = await getCronCapabilities();
      sendJson(res, 200, capabilities);
    } catch (error) {
      sendError(res, error);
    }
    return;
  }

  if (url.pathname.startsWith("/api/cron-jobs/") && url.pathname.endsWith("/pause") && method === "PUT") {
    try {
      const sourceId = decodeURIComponent(url.pathname.replace("/api/cron-jobs/", "").replace("/pause", "")).trim();
      if (!sourceId) {
        sendJson(res, 400, { error: "Cron source id is required" });
        return;
      }

      const body = await readJsonBody(req);
      const paused = Boolean(body?.paused);
      const result = await setCronPaused(sourceId, paused);
      sendJson(res, 200, { ok: true, ...result });
    } catch (error) {
      sendError(res, error);
    }
    return;
  }

  if (url.pathname.startsWith("/api/cron-jobs/") && method === "PUT") {
    try {
      const sourceId = decodeURIComponent(url.pathname.replace("/api/cron-jobs/", "")).trim();
      if (!sourceId) {
        sendJson(res, 400, { error: "Cron source id is required" });
        return;
      }

      const body = await readJsonBody(req);
      const schedule = String(body?.schedule || "").trim();
      const prompt = String(body?.prompt || "").trim();
      const targetAgent = String(body?.targetAgent || "").trim();
      const targetSession = String(body?.targetSession || "").trim();
      const priority = Number.isFinite(Number(body?.priority)) ? Number(body.priority) : 0;
      const paused = Boolean(body?.paused);

      if (!schedule || !prompt || !targetAgent) {
        sendJson(res, 400, { error: "schedule, prompt, and targetAgent are required" });
        return;
      }

      const saved = await upsertCronJob(sourceId, {
        schedule,
        prompt,
        target_agent: targetAgent,
        target_session: targetSession,
        priority,
        paused,
      });
      sendJson(res, 200, { ok: true, cronJob: saved });
    } catch (error) {
      sendError(res, error);
    }
    return;
  }

  if (url.pathname.startsWith("/api/cron-jobs/") && method === "DELETE") {
    try {
      const sourceId = decodeURIComponent(url.pathname.replace("/api/cron-jobs/", "")).trim();
      if (!sourceId) {
        sendJson(res, 400, { error: "Cron source id is required" });
        return;
      }

      await deleteCronJob(sourceId);
      sendJson(res, 200, { ok: true, sourceId });
    } catch (error) {
      sendError(res, error);
    }
    return;
  }

  // Webhook sources
  if (url.pathname === "/api/webhooks" && method === "GET") {
    try {
      const webhooks = await listWebhooks();
      sendJson(res, 200, { webhooks });
    } catch (error) {
      sendError(res, error);
    }
    return;
  }

  if (url.pathname.startsWith("/api/webhooks/") && url.pathname.endsWith("/pause") && method === "POST") {
    try {
      const sourceId = decodeURIComponent(url.pathname.replace("/api/webhooks/", "").replace("/pause", "")).trim();
      if (!sourceId) {
        sendJson(res, 400, { error: "Webhook source id is required" });
        return;
      }

      const body = await readJsonBody(req);
      const paused = Boolean(body?.paused);
      const updated = await setWebhookPaused(sourceId, paused);
      sendJson(res, 200, { ok: true, updated });
    } catch (error) {
      sendError(res, error);
    }
    return;
  }

  if (url.pathname.startsWith("/api/webhooks/") && method === "PUT") {
    try {
      const sourceId = decodeURIComponent(url.pathname.replace("/api/webhooks/", "")).trim();
      if (!sourceId) {
        sendJson(res, 400, { error: "Webhook source id is required" });
        return;
      }

      const body = await readJsonBody(req);
      const { promptTemplate, targetAgent, targetSession, priority, paused, secretEnv } = body;
      if (!targetAgent) {
        sendJson(res, 400, { error: "targetAgent is required" });
        return;
      }
      if (!String(secretEnv || "").trim()) {
        sendJson(res, 400, { error: "secretEnv is required for webhook security" });
        return;
      }

      const saved = await upsertWebhook(sourceId, {
        prompt_template: promptTemplate || "",
        target_agent: targetAgent,
        target_session: targetSession || "",
        priority: Number.parseInt(priority || "0", 10),
        paused: Boolean(paused),
        secret_env: secretEnv || "",
      });
      sendJson(res, 200, { ok: true, webhook: saved });
    } catch (error) {
      sendError(res, error);
    }
    return;
  }

  if (url.pathname.startsWith("/api/webhooks/") && method === "DELETE") {
    try {
      const sourceId = decodeURIComponent(url.pathname.replace("/api/webhooks/", "")).trim();
      if (!sourceId) {
        sendJson(res, 400, { error: "Webhook source id is required" });
        return;
      }

      await deleteWebhook(sourceId);
      sendJson(res, 200, { ok: true, sourceId });
    } catch (error) {
      sendError(res, error);
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
  const gatewaySession = createGatewaySessionController(ws);

  gatewaySession
    .start()
    .catch((error) => {
      if (ws.readyState === ws.OPEN) {
        ws.send(JSON.stringify({ type: "bridge_stderr", content: `Gateway mode error: ${String(error)}` }));
        ws.close();
      }
    });

  ws.on("message", (raw) => {
    gatewaySession.onMessage(raw).catch((error) => {
      if (ws.readyState === ws.OPEN) {
        ws.send(JSON.stringify({ type: "bridge_stderr", content: String(error) }));
      }
    });
  });

  ws.on("close", () => {
    gatewaySession.onClose();
  });
});

initApiKeyDb()
  .then(async () => {
    await ensureGatewayReady();
    gatewayEnabled = true;
    server.listen(port, () => {
      console.log(`Proxi React frontend running at http://localhost:${port} using gateway (${gatewayBaseUrl})`);
    });
  })
  .catch((error) => {
    console.error(`Failed to initialize API key database: ${String(error)}`);
    process.exit(1);
  });
