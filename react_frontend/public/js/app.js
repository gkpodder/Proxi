const { useEffect, useMemo, useRef, useState } = React;
const { ChatView, BootstrapModal, AskUserQuestionModal, SettingsModal } = window.ProxiComponents;
const {
  OTHER_OPTION,
  renderMarkdown,
  getVisibleQuestions,
  getOptionsWithOther,
} = window.ProxiUtils;

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

function App() {
  const [socketState, setSocketState] = useState("connecting");
  const [statusLabel, setStatusLabel] = useState("Starting...");
  const [messages, setMessages] = useState([]);
  const [activityItems, setActivityItems] = useState([]);
  const [streaming, setStreaming] = useState("");
  const [input, setInput] = useState("");
  const [bootInfo, setBootInfo] = useState(null);
  const [bootstrapInput, setBootstrapInput] = useState(null);
  const [formUi, setFormUi] = useState(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [darkMode, setDarkMode] = useState(true);
  const [apiKeys, setApiKeys] = useState([]);
  const [keysLoading, setKeysLoading] = useState(false);
  const [keysSaving, setKeysSaving] = useState(false);
  const [keyDrafts, setKeyDrafts] = useState({});
  const [newKeyName, setNewKeyName] = useState("");
  const [newKeyValue, setNewKeyValue] = useState("");
  const [keyFeedback, setKeyFeedback] = useState("");
  const [mcps, setMcps] = useState([]);
  const [mcpsLoading, setMcpsLoading] = useState(false);
  const [mcpsSaving, setMcpsSaving] = useState(false);
  const [mcpFeedback, setMcpFeedback] = useState("");
  const [profile, setProfile] = useState({
    name: "",
    location: "",
    timezone: "",
    age: "",
    occupation: "",
    email: "",
    email_signature: "",
    demographics: "",
  });
  const [profileLoading, setProfileLoading] = useState(false);
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileFeedback, setProfileFeedback] = useState("");

  const hasSelectedAgent = !!bootInfo;
  const isPromptActive = !!bootstrapInput || !!formUi;
  const canInteract = socketState === "connected" && hasSelectedAgent && !isPromptActive;

  const wsRef = useRef(null);
  const chatRef = useRef(null);
  const recognizerRef = useRef(null);
  const pendingMcpActivityRef = useRef({});

  const visibleQuestions = useMemo(() => {
    if (!formUi) return [];
    return getVisibleQuestions(formUi.payload.questions, formUi.answers);
  }, [formUi]);

  const currentQuestion = useMemo(() => {
    if (!formUi || visibleQuestions.length === 0) return null;
    const safeIndex = Math.min(formUi.currentIndex, Math.max(0, visibleQuestions.length - 1));
    return visibleQuestions[safeIndex] || null;
  }, [formUi, visibleQuestions]);

  const currentOptions = useMemo(() => getOptionsWithOther(currentQuestion), [currentQuestion]);

  useEffect(() => {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${protocol}://${window.location.host}/bridge`);
    wsRef.current = ws;

    ws.onopen = () => {
      setSocketState("connected");
      addSystem("Connected to bridge relay.");
    };

    ws.onclose = () => {
      setSocketState("closed");
      commitStream();
      addSystem("Bridge connection closed.");
    };

    ws.onerror = () => {
      addError("WebSocket error.");
    };

    ws.onmessage = (evt) => {
      let msg;
      try {
        msg = JSON.parse(evt.data);
      } catch {
        return;
      }
      handleMessage(msg);
    };

    return () => {
      ws.close();
    };
  }, []);

  useEffect(() => {
    if (!chatRef.current) return;
    chatRef.current.scrollTop = chatRef.current.scrollHeight;
  }, [messages, streaming]);

  useEffect(() => {
    if (!settingsOpen) return;
    loadApiKeys();
    loadMcps();
    loadUserProfile();
  }, [settingsOpen]);

  async function loadUserProfile() {
    setProfileLoading(true);
    setProfileFeedback("");
    try {
      const response = await fetch("/api/profile");
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Failed to load profile");

      const saved = payload.profile || {};
      setProfile({
        name: String(saved.name || ""),
        location: String(saved.location || ""),
        timezone: String(saved.timezone || ""),
        age: saved.age === 0 || saved.age ? String(saved.age) : "",
        occupation: String(saved.occupation || ""),
        email: String(saved.email || ""),
        email_signature: String(saved.email_signature || ""),
        demographics: String(saved.demographics || ""),
      });
    } catch (error) {
      setProfileFeedback(`Error: ${String(error)}`);
    } finally {
      setProfileLoading(false);
    }
  }

  async function saveUserProfile() {
    const trimmedProfile = {
      name: profile.name.trim(),
      location: profile.location.trim(),
      timezone: profile.timezone.trim(),
      age: profile.age.trim(),
      occupation: profile.occupation.trim(),
      email: profile.email.trim(),
      email_signature: profile.email_signature.trim(),
      demographics: profile.demographics.trim(),
    };

    const ageNumber = trimmedProfile.age ? Number.parseInt(trimmedProfile.age, 10) : null;
    if (trimmedProfile.age && (!Number.isFinite(ageNumber) || ageNumber <= 0)) {
      setProfileFeedback("Error: age must be a positive whole number.");
      return;
    }

    const payloadProfile = { ...trimmedProfile, age: ageNumber };

    setProfileSaving(true);
    setProfileFeedback("");
    try {
      const response = await fetch("/api/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profile: payloadProfile }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Failed to save profile");

      setProfileFeedback("Profile saved. New responses will use this context.");
      await loadUserProfile();
    } catch (error) {
      setProfileFeedback(`Error: ${String(error)}`);
    } finally {
      setProfileSaving(false);
    }
  }

  async function clearUserProfile() {
    const confirmed = window.confirm("Delete all saved profile information?");
    if (!confirmed) return;

    setProfileSaving(true);
    setProfileFeedback("");
    try {
      const response = await fetch("/api/profile", { method: "DELETE" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Failed to delete profile");

      setProfile({
        name: "",
        location: "",
        timezone: "",
        age: "",
        occupation: "",
        email: "",
        email_signature: "",
        demographics: "",
      });
      setProfileFeedback(
        "Profile deleted from DB. Deletion takes effect from the next session, and current context may still include previously loaded profile info."
      );
    } catch (error) {
      setProfileFeedback(`Error: ${String(error)}`);
    } finally {
      setProfileSaving(false);
    }
  }

  function updateProfileField(field, value) {
    setProfile((prev) => ({ ...prev, [field]: value }));
  }

  async function loadApiKeys() {
    setKeysLoading(true);
    setKeyFeedback("");
    try {
      const response = await fetch("/api/keys");
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Failed to load API keys");
      setApiKeys(Array.isArray(payload.keys) ? payload.keys : []);
    } catch (error) {
      setKeyFeedback(`Error: ${String(error)}`);
    } finally {
      setKeysLoading(false);
    }
  }

  async function loadMcps() {
    setMcpsLoading(true);
    setMcpFeedback("");
    try {
      const response = await fetch("/api/mcps");
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Failed to load MCPs");
      setMcps(Array.isArray(payload.mcps) ? payload.mcps : []);
    } catch (error) {
      setMcpFeedback(`Error: ${String(error)}`);
    } finally {
      setMcpsLoading(false);
    }
  }

  async function toggleMcp(mcpName, enabled) {
    setMcpsSaving(true);
    setMcpFeedback("");
    try {
      const response = await fetch(`/api/mcps/${encodeURIComponent(mcpName)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !enabled }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Failed to update MCP");

      const action = !enabled ? "enabled" : "disabled";
      setMcpFeedback(`${mcpName} has been ${action}. Restart the agent for changes to take effect.`);
      await loadMcps();
    } catch (error) {
      setMcpFeedback(`Error: ${String(error)}`);
    } finally {
      setMcpsSaving(false);
    }
  }

  async function saveKey(keyName, value) {
    const normalized = (keyName || "").trim().toUpperCase();
    const cleanValue = (value || "").trim();
    if (!normalized || !cleanValue) {
      setKeyFeedback("Key name and value are required.");
      return;
    }

    setKeysSaving(true);
    setKeyFeedback("");
    try {
      const response = await fetch(`/api/keys/${encodeURIComponent(normalized)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: cleanValue }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Failed to save API key");

      setKeyDrafts((prev) => ({ ...prev, [normalized]: "" }));
      setNewKeyName("");
      setNewKeyValue("");
      setKeyFeedback(`Saved ${normalized}. New sessions will use this key.`);
      await loadApiKeys();
    } catch (error) {
      setKeyFeedback(`Error: ${String(error)}`);
    } finally {
      setKeysSaving(false);
    }
  }

  function addSystem(content) {
    addActivity("system", "System", content);
  }

  function addError(content) {
    setMessages((prev) => [...prev, { role: "error", content }]);
  }

  function addUser(content) {
    setMessages((prev) => [...prev, { role: "user", content }]);
  }

  function addAssistant(content) {
    setMessages((prev) => [...prev, { role: "assistant", content }]);
  }

  function addActivity(kind, title, content = "") {
    const item = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      kind,
      title,
      content,
      at: new Date().toLocaleTimeString(),
    };
    setActivityItems((prev) => [...prev.slice(-199), item]);
    return item.id;
  }

  function updateActivityById(activityId, updater) {
    if (!activityId) return;
    setActivityItems((prev) => prev.map((item) => (item.id === activityId ? updater(item) : item)));
  }

  function isMcpToolName(toolName) {
    return typeof toolName === "string" && toolName.toLowerCase().startsWith("mcp_");
  }

  function recordThinking(content) {
    if (!content || typeof content !== "string") return;
    addActivity("thinking", "Model thinking", content);
  }

  function commitStream() {
    setStreaming((prev) => {
      if (prev) addAssistant(prev);
      return "";
    });
  }

  function send(payload) {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      addError("Bridge is not connected.");
      return;
    }
    ws.send(JSON.stringify(payload));
  }

  function onSwitchAgent() {
    if (isPromptActive) {
      addSystem("Complete the current prompt first.");
      return;
    }
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      addError("Bridge is not connected.");
      return;
    }
    wsRef.current.send(JSON.stringify({ type: "switch_agent" }));
    commitStream();
    addSystem("Switching agent...");
    setStatusLabel("Switching...");
    setBootInfo(null);
    setBootstrapInput(null);
    setFormUi(null);
  }

  function handleMessage(msg) {
    if (typeof msg?.reasoning === "string" && msg.reasoning.trim()) {
      recordThinking(msg.reasoning.trim());
    }

    switch (msg.type) {
      case "ready":
        setStatusLabel("Bridge ready");
        addSystem("Bridge ready.");
        break;
      case "boot_complete":
        setBootInfo({ agentId: msg.agentId, sessionId: msg.sessionId });
        setBootstrapInput(null);
        break;
      case "text_stream":
        setStreaming((prev) => prev + (msg.content || ""));
        break;
      case "status_update":
        if (msg.status === "running") {
          setStatusLabel(msg.label ? `Running: ${msg.label}` : "Running...");
          if (msg.label && /thinking|reasoning/i.test(msg.label)) {
            addActivity("thinking", "Thinking", msg.label);
          }
        } else if (msg.status === "done") {
          setStatusLabel("Idle");
          commitStream();
        }
        break;
      case "tool_start": {
        const toolName = msg.tool || "Unknown tool";
        const argsText = msg.arguments ? JSON.stringify(msg.arguments) : "";
        if (isMcpToolName(toolName)) {
          const mcpId = addActivity("mcp", `Start: ${toolName}`, argsText || "Status: running");
          pendingMcpActivityRef.current[toolName] = mcpId;
        } else {
          addActivity("tool", `Start: ${toolName}`, argsText);
        }
        break;
      }
      case "tool_log": {
        const content = msg.content || "";
        if (/thinking|reasoning/i.test(content)) {
          addActivity("thinking", "Thinking", content);
        } else {
          addActivity("tool", "Tool log", content);
        }
        break;
      }
      case "tool_done": {
        const toolName = msg.tool || "Unknown tool";
        const status = msg.success ? "success" : "error";
        if (isMcpToolName(toolName)) {
          const pendingId = pendingMcpActivityRef.current[toolName];
          const statusLine = `Status: ${msg.success ? "successful" : "failed"}`;

          if (pendingId) {
            updateActivityById(pendingId, (existing) => ({
              ...existing,
              title: `${toolName}`,
              content: existing.content ? `${existing.content}\n${statusLine}` : statusLine,
              at: new Date().toLocaleTimeString(),
            }));
            delete pendingMcpActivityRef.current[toolName];
          } else {
            addActivity("mcp", toolName, statusLine);
          }
        } else {
          const details = msg.error || msg.output || "";
          addActivity("tool", `Done (${status}): ${toolName}`, details);
        }
        break;
      }
      case "subagent_start":
        addActivity("tool", `Subagent start: ${msg.agent || "unknown"}`, msg.task || "");
        break;
      case "subagent_done":
        addActivity(
          "tool",
          `Subagent done: ${msg.agent || "unknown"}`,
          msg.success ? "Completed successfully" : "Completed with errors"
        );
        break;
      case "thinking":
      case "reasoning":
      case "thinking_stream":
        recordThinking(msg.content || msg.text || "");
        break;
      case "user_input_required":
        commitStream();
        handleUserInputRequired(msg);
        break;
      case "bridge_stderr":
        addError(`Bridge stderr: ${msg.content}`);
        break;
      case "bridge_exit":
        addError(`Bridge exited (code=${msg.code ?? "null"}).`);
        setStatusLabel("Bridge stopped");
        break;
      default:
        break;
    }
  }

  function handleUserInputRequired(msg) {
    if (msg.payload && Array.isArray(msg.payload.questions)) {
      setFormUi({
        payload: msg.payload,
        answers: {},
        currentIndex: 0,
        selectIndex: 0,
        multiselect: [],
        textValue: "",
        otherValue: "",
      });
      return;
    }

    const method = msg.method || "text";
    const prompt = msg.prompt || "Input required";
    const options = Array.isArray(msg.options) ? msg.options : [];
    setBootstrapInput({
      method,
      prompt,
      options,
      textValue: "",
      selectIndex: 0,
    });
  }

  function submitBootstrap(value) {
    send({ type: "user_input", value });
    setBootstrapInput(null);
  }

  function skipBootstrap() {
    submitBootstrap(false);
  }

  function toggleMultiselect(index) {
    setFormUi((prev) => {
      if (!prev) return prev;
      const exists = prev.multiselect.includes(index);
      return {
        ...prev,
        multiselect: exists ? prev.multiselect.filter((i) => i !== index) : [...prev.multiselect, index],
      };
    });
  }

  function submitCollaborative(answers, skipped) {
    if (!formUi) return;
    send({
      type: "user_input_response",
      payload: {
        tool_call_id: formUi.payload.tool_call_id,
        answers,
        skipped,
      },
    });
    setFormUi(null);
  }

  function goFormBack() {
    setFormUi((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        currentIndex: Math.max(0, prev.currentIndex - 1),
        selectIndex: 0,
        multiselect: [],
        textValue: "",
        otherValue: "",
      };
    });
  }

  function advanceForm() {
    if (!formUi || !currentQuestion) return;

    const required = currentQuestion.required !== false;
    let value;

    if (currentQuestion.type === "yesno") {
      value = formUi.answers[currentQuestion.id];
      if (required && typeof value === "undefined") return;
    }

    if (currentQuestion.type === "choice") {
      const selected = currentOptions[formUi.selectIndex];
      if (!selected) return;
      value = selected === OTHER_OPTION ? formUi.otherValue.trim() : selected;
      if (required && !value) return;
    }

    if (currentQuestion.type === "multiselect") {
      const selected = formUi.multiselect
        .map((i) => currentOptions[i])
        .filter(Boolean)
        .map((opt) => (opt === OTHER_OPTION ? formUi.otherValue.trim() : opt))
        .filter((opt) => !!opt);
      value = selected;
      if (required && selected.length === 0) return;
    }

    if (currentQuestion.type === "text") {
      value = formUi.textValue.trim();
      if (required && !value) return;
    }

    const mergedAnswers = { ...formUi.answers, [currentQuestion.id]: value };
    const nextVisible = getVisibleQuestions(formUi.payload.questions, mergedAnswers);
    if (nextVisible.length === 0) {
      submitCollaborative(mergedAnswers, false);
      return;
    }

    const isLast = formUi.currentIndex >= nextVisible.length - 1;
    if (isLast) {
      submitCollaborative(mergedAnswers, false);
      return;
    }

    setFormUi((prev) => {
      if (!prev) return prev;
      const clamped = Math.min(prev.currentIndex + 1, Math.max(0, nextVisible.length - 1));
      return {
        ...prev,
        answers: mergedAnswers,
        currentIndex: clamped,
        selectIndex: 0,
        multiselect: [],
        textValue: "",
        otherValue: "",
      };
    });
  }

  function onSend() {
    const task = input.trim();
    if (isPromptActive) {
      addSystem("Complete the current prompt first.");
      return;
    }
    if (!hasSelectedAgent) {
      addSystem("Select an agent first.");
      return;
    }
    if (!task) return;

    addUser(task);
    setInput("");
    setStatusLabel("Running...");
    setStreaming("");
    send({ type: "start", task });
  }

  function onAbort() {
    if (isPromptActive) {
      addSystem("Complete the current prompt first.");
      return;
    }
    if (!hasSelectedAgent) {
      addSystem("Select an agent first.");
      return;
    }

    send({ type: "abort" });
    commitStream();
    addSystem("Request aborted.");
    setStatusLabel("Idle");
  }

  function onKeyDown(evt) {
    if (evt.key === "Enter" && !evt.shiftKey) {
      evt.preventDefault();
      onSend();
    }
  }

  function onMicClick() {
    if (isPromptActive) {
      addSystem("Complete the current prompt first.");
      return;
    }
    if (!hasSelectedAgent) {
      addSystem("Select an agent first.");
      return;
    }
    if (!SpeechRecognition) {
      alert("Speech Recognition not supported in this browser.");
      return;
    }

    if (isListening) {
      recognizerRef.current?.stop();
      setIsListening(false);
      return;
    }

    if (!recognizerRef.current) {
      recognizerRef.current = new SpeechRecognition();
      recognizerRef.current.continuous = false;
      recognizerRef.current.interimResults = true;
      recognizerRef.current.lang = "en-US";

      recognizerRef.current.onstart = () => setIsListening(true);
      recognizerRef.current.onresult = (evt) => {
        for (let i = evt.resultIndex; i < evt.results.length; i++) {
          const transcript = evt.results[i][0].transcript;
          if (evt.results[i].isFinal) {
            setInput((prev) => prev + (prev ? " " : "") + transcript);
          }
        }
      };
      recognizerRef.current.onerror = (evt) => {
        addError(`Speech error: ${evt.error}`);
        setIsListening(false);
      };
      recognizerRef.current.onend = () => setIsListening(false);
    }

    recognizerRef.current.start();
  }

  const connectionText = useMemo(() => {
    if (socketState === "connected") return "Connected";
    if (socketState === "closed") return "Disconnected";
    return "Connecting...";
  }, [socketState]);

  return (
    <div className={`app ${darkMode ? "dark" : "light"}`}>
      <div className="header">
        <div className="headerTitle">Proxi</div>
        <div className="headerControls">
          <button className="settingsBtn" onClick={() => setSettingsOpen(true)}>
            Settings
          </button>
          <button
            className="themeToggle"
            onClick={() => setDarkMode(!darkMode)}
            title={darkMode ? "Switch to light theme" : "Switch to dark theme"}
            aria-label={darkMode ? "Switch to light theme" : "Switch to dark theme"}
          >
            <i className={`fa-solid ${darkMode ? "fa-sun" : "fa-moon"}`} aria-hidden="true"></i>
          </button>
          <button
            className="switchAgentBtn"
            onClick={onSwitchAgent}
            disabled={socketState !== "connected" || isPromptActive}
            title="Switch to a different agent"
            aria-label="Switch to a different agent"
          >
            <i className="fa-solid fa-arrows-rotate" aria-hidden="true"></i>
          </button>
          <div className="headerStatus">
            <span className={`statusDot ${socketState}`}></span>
            {connectionText} - {statusLabel}
          </div>
        </div>
      </div>

      <ChatView
        chatRef={chatRef}
        messages={messages}
        activityItems={activityItems}
        streaming={streaming}
        renderMarkdown={renderMarkdown}
        bootInfo={bootInfo}
        input={input}
        setInput={setInput}
        onKeyDown={onKeyDown}
        hasSelectedAgent={hasSelectedAgent}
        canInteract={canInteract}
        isListening={isListening}
        onMicClick={onMicClick}
        onSend={onSend}
        onAbort={onAbort}
      />

      <SettingsModal
        isOpen={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        bootInfo={bootInfo}
        socketState={socketState}
        isPromptActive={isPromptActive}
        onSwitchAgent={onSwitchAgent}
        profile={profile}
        profileLoading={profileLoading}
        profileSaving={profileSaving}
        profileFeedback={profileFeedback}
        updateProfileField={updateProfileField}
        saveUserProfile={saveUserProfile}
        clearUserProfile={clearUserProfile}
        loadUserProfile={loadUserProfile}
        keysLoading={keysLoading}
        keysSaving={keysSaving}
        keyFeedback={keyFeedback}
        apiKeys={apiKeys}
        keyDrafts={keyDrafts}
        setKeyDrafts={setKeyDrafts}
        newKeyName={newKeyName}
        setNewKeyName={setNewKeyName}
        newKeyValue={newKeyValue}
        setNewKeyValue={setNewKeyValue}
        saveKey={saveKey}
        loadApiKeys={loadApiKeys}
        mcpsLoading={mcpsLoading}
        mcpsSaving={mcpsSaving}
        mcpFeedback={mcpFeedback}
        mcps={mcps}
        toggleMcp={toggleMcp}
        loadMcps={loadMcps}
      />

      <BootstrapModal
        bootstrapInput={bootstrapInput}
        setBootstrapInput={setBootstrapInput}
        submitBootstrap={submitBootstrap}
        skipBootstrap={skipBootstrap}
      />

      <AskUserQuestionModal
        formUi={formUi}
        currentQuestion={currentQuestion}
        visibleQuestions={visibleQuestions}
        currentOptions={currentOptions}
        setFormUi={setFormUi}
        toggleMultiselect={toggleMultiselect}
        goFormBack={goFormBack}
        submitCollaborative={submitCollaborative}
        advanceForm={advanceForm}
      />
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
