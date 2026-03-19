const { useEffect, useMemo, useRef, useState } = React;

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

marked.setOptions({ gfm: true, breaks: false });
function renderMarkdown(text) {
  if (!text) return "";
  const raw = marked.parse(text);
  return DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } });
}
const OTHER_OPTION = "Other (type your own)";

function evaluateShowIf(showIf, answers) {
  if (!showIf) return true;
  const qId = showIf.question_id;
  if (!qId || !(qId in answers)) return false;
  const answer = answers[qId];
  if (Object.prototype.hasOwnProperty.call(showIf, "equals")) return answer === showIf.equals;
  if (Object.prototype.hasOwnProperty.call(showIf, "not_equals")) return answer !== showIf.not_equals;
  return true;
}

function getVisibleQuestions(questions, answers) {
  return (questions || []).filter((q) => evaluateShowIf(q.show_if, answers));
}

function getOptionsWithOther(question) {
  if (!question) return [];
  if (question.type === "choice" || question.type === "multiselect") {
    return [...(question.options || []), OTHER_OPTION];
  }
  return [];
}

const TIMEZONE_OPTIONS = [
  "America/Toronto",
  "America/Vancouver",
  "America/New_York",
  "America/Los_Angeles",
  "Europe/London",
  "Europe/Berlin",
  "Asia/Kolkata",
  "Asia/Tokyo",
  "Australia/Sydney",
  "UTC",
];

function App() {
  const [currentPage, setCurrentPage] = useState("chat");
  const [socketState, setSocketState] = useState("connecting");
  const [statusLabel, setStatusLabel] = useState("Starting...");
  const [messages, setMessages] = useState([]);
  const [streaming, setStreaming] = useState("");
  const [input, setInput] = useState("");
  const [bootInfo, setBootInfo] = useState(null);
  const [bootstrapInput, setBootstrapInput] = useState(null);
  const [formUi, setFormUi] = useState(null);
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
    if (currentPage !== "settings") return;
    loadApiKeys();
    loadMcps();
    loadUserProfile();
  }, [currentPage]);

  async function loadUserProfile() {
    setProfileLoading(true);
    setProfileFeedback("");
    try {
      const response = await fetch("/api/profile");
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Failed to load profile");
      }

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

    const payloadProfile = {
      ...trimmedProfile,
      age: ageNumber,
    };

    setProfileSaving(true);
    setProfileFeedback("");
    try {
      const response = await fetch("/api/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profile: payloadProfile }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Failed to save profile");
      }

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
      if (!response.ok) {
        throw new Error(payload.error || "Failed to delete profile");
      }

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
      if (!response.ok) {
        throw new Error(payload.error || "Failed to load API keys");
      }
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
      if (!response.ok) {
        throw new Error(payload.error || "Failed to load MCPs");
      }
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
      if (!response.ok) {
        throw new Error(payload.error || "Failed to update MCP");
      }

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
      if (!response.ok) {
        throw new Error(payload.error || "Failed to save API key");
      }

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
    setMessages((prev) => [...prev, { role: "system", content }]);
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
        } else if (msg.status === "done") {
          setStatusLabel("Idle");
          commitStream();
        }
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
        multiselect: exists
          ? prev.multiselect.filter((i) => i !== index)
          : [...prev.multiselect, index],
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

      recognizerRef.current.onstart = () => {
        setIsListening(true);
      };

      recognizerRef.current.onresult = (evt) => {
        let interim = "";
        for (let i = evt.resultIndex; i < evt.results.length; i++) {
          const transcript = evt.results[i][0].transcript;
          if (evt.results[i].isFinal) {
            setInput((prev) => prev + (prev ? " " : "") + transcript);
          } else {
            interim += transcript;
          }
        }
      };

      recognizerRef.current.onerror = (evt) => {
        addError(`Speech error: ${evt.error}`);
        setIsListening(false);
      };

      recognizerRef.current.onend = () => {
        setIsListening(false);
      };
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
        <div className="headerTitle">✨ Proxi</div>
        <div className="headerControls">
          <div className="pageTabs">
            <button
              className={`tabBtn ${currentPage === "chat" ? "active" : ""}`}
              onClick={() => setCurrentPage("chat")}
            >
              Chat
            </button>
            <button
              className={`tabBtn ${currentPage === "settings" ? "active" : ""}`}
              onClick={() => setCurrentPage("settings")}
            >
              Settings
            </button>
          </div>
          <div className="headerStatus">
            <span className={`statusDot ${socketState}`}></span>
            {connectionText} · {statusLabel}
          </div>
          <button
            className="themeToggle"
            onClick={() => setDarkMode(!darkMode)}
            title="Toggle dark mode"
          >
            {darkMode ? "☀️" : "🌙"}
          </button>
          <button
            className="switchAgentBtn"
            onClick={onSwitchAgent}
            disabled={socketState !== "connected" || isPromptActive}
            title="Switch to a different agent"
          >
            🔄
          </button>
        </div>
      </div>

      {currentPage === "chat" && (
        <>
          <div className="chat" ref={chatRef}>
            {messages.map((m, i) => {
              const displayRole = m.role === "assistant" ? "proxi" : m.role;
              const isMarkdown = m.role === "assistant";
              return (
                <div key={i} className={`msg ${m.role}`}>
                  <span className="role">{displayRole}</span>
                  {isMarkdown
                    ? <span className="content md" dangerouslySetInnerHTML={{ __html: renderMarkdown(m.content) }} />
                    : <span className="content">{m.content}</span>
                  }
                </div>
              );
            })}
            {streaming && (
              <div className="msg assistant">
                <span className="role">proxi</span>
                <span className="content md" dangerouslySetInnerHTML={{ __html: renderMarkdown(streaming) }} />
              </div>
            )}
          </div>

          <div className="footer-wrapper">
            <div className="footer">
              {bootInfo && (
                <div className="bootInfo">
                  Agent: <strong>{bootInfo.agentId}</strong> · Session:{" "}
                  <strong>{bootInfo.sessionId.slice(0, 8)}</strong>
                </div>
              )}
              <div className="inputRow">
                <input
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={onKeyDown}
                  placeholder={hasSelectedAgent ? "Ask anything or click 🎤 to speak..." : "Select an agent first..."}
                  disabled={!canInteract}
                />
                <button
                  className={`micBtn ${isListening ? "listening" : ""}`}
                  onClick={onMicClick}
                  disabled={!canInteract}
                  title="Click to start/stop listening"
                >
                  {isListening ? "⏹️" : "🎤"}
                </button>
                <button onClick={onSend} disabled={!canInteract}>
                  Send
                </button>
                <button onClick={onAbort} disabled={!canInteract}>
                  Abort
                </button>
              </div>
            </div>
          </div>
        </>
      )}

      {currentPage === "settings" && (
        <div className="settingsPage">
          <div className="settingsCard">
            <h2 className="settingsTitle">Agent</h2>
            <div className="settingsHint">Switch agents between tasks.</div>
            <div className="settingsRow">
              <div>
                <div className="settingsLabel">Current agent</div>
                <div className="settingsValue">{bootInfo?.agentId || "Not selected"}</div>
              </div>
              <button
                className="primaryBtn"
                onClick={onSwitchAgent}
                disabled={socketState !== "connected" || isPromptActive}
              >
                Switch Agent
              </button>
            </div>
          </div>

          <div className="settingsCard">
            <h2 className="settingsTitle">Profile</h2>
            <div className="settingsHint">
              Used to personalize replies like email signatures and timezone-aware suggestions.
            </div>
            <div className="settingsHint">
              If you delete your profile, deletion takes effect from the next session; current context may still include already loaded profile info.
            </div>

            {profileLoading ? (
              <div className="formHint">Loading profile...</div>
            ) : (
              <div className="profileGrid">
                <label className="profileField">
                  <span>Name</span>
                  <input
                    type="text"
                    value={profile.name}
                    onChange={(e) => updateProfileField("name", e.target.value)}
                    placeholder="Your full name"
                  />
                </label>
                <label className="profileField">
                  <span>Location</span>
                  <input
                    type="text"
                    value={profile.location}
                    onChange={(e) => updateProfileField("location", e.target.value)}
                    placeholder="City, Country"
                  />
                </label>
                <label className="profileField">
                  <span>Timezone</span>
                  <select
                    className="profileSelect"
                    value={profile.timezone}
                    onChange={(e) => updateProfileField("timezone", e.target.value)}
                  >
                    <option value="">Select timezone</option>
                    {TIMEZONE_OPTIONS.map((tz) => (
                      <option key={tz} value={tz}>{tz}</option>
                    ))}
                  </select>
                </label>
                <label className="profileField">
                  <span>Age</span>
                  <input
                    type="text"
                    value={profile.age}
                    onChange={(e) => updateProfileField("age", e.target.value)}
                    placeholder="21"
                  />
                </label>
                <label className="profileField">
                  <span>Occupation</span>
                  <input
                    type="text"
                    value={profile.occupation}
                    onChange={(e) => updateProfileField("occupation", e.target.value)}
                    placeholder="Student, Engineer, Designer..."
                  />
                </label>
                <label className="profileField">
                  <span>Email</span>
                  <input
                    type="text"
                    value={profile.email}
                    onChange={(e) => updateProfileField("email", e.target.value)}
                    placeholder="you@example.com"
                  />
                </label>
                <label className="profileField profileFieldFull">
                  <span>Preferred Email Signature</span>
                  <input
                    type="text"
                    value={profile.email_signature}
                    onChange={(e) => updateProfileField("email_signature", e.target.value)}
                    placeholder="Best regards, Name"
                  />
                </label>
                <label className="profileField profileFieldFull">
                  <span>Additional Demographics</span>
                  <textarea
                    className="formTextarea"
                    value={profile.demographics}
                    onChange={(e) => updateProfileField("demographics", e.target.value)}
                    placeholder="Share any context you want Proxi to consider (optional)."
                  />
                </label>
              </div>
            )}

            {profileFeedback && <div className="formHint">{profileFeedback}</div>}
            <div className="formActions">
              <button className="primaryBtn" onClick={saveUserProfile} disabled={profileLoading || profileSaving}>
                Save Profile
              </button>
              <button onClick={clearUserProfile} disabled={profileLoading || profileSaving}>
                Clear Profile
              </button>
              <button onClick={() => loadUserProfile()} disabled={profileLoading || profileSaving}>
                Refresh
              </button>
            </div>
          </div>

          <div className="settingsCard">
            <h2 className="settingsTitle">API Keys</h2>
            <div className="settingsHint">Keys are stored in SQLite and injected when the bridge starts.</div>
            {keysLoading ? (
              <div className="formHint">Loading keys...</div>
            ) : (
              <div className="keyList">
                {apiKeys.length === 0 && <div className="formHint">No keys saved yet.</div>}
                {apiKeys.map((item) => (
                  <div key={item.key_name} className="keyRow">
                    <div className="keyMeta">
                      <div className="keyName">{item.key_name}</div>
                      <div className="keyMasked">Current: {item.masked_value}</div>
                    </div>
                    <input
                      type="text"
                      className="keyInput"
                      value={keyDrafts[item.key_name] || ""}
                      placeholder="Enter new value to replace"
                      onChange={(e) =>
                        setKeyDrafts((prev) => ({ ...prev, [item.key_name]: e.target.value }))
                      }
                    />
                    <button
                      className="primaryBtn"
                      disabled={keysSaving || !(keyDrafts[item.key_name] || "").trim()}
                      onClick={() => saveKey(item.key_name, keyDrafts[item.key_name])}
                    >
                      Save
                    </button>
                  </div>
                ))}
              </div>
            )}

            <div className="keyAddSection">
              <div className="keyAddTitle">Add New Key</div>
              <div className="keyAddRow">
                <input
                  type="text"
                  className="keyInput"
                  value={newKeyName}
                  placeholder="Example: OPENAI_API_KEY"
                  onChange={(e) => setNewKeyName(e.target.value)}
                />
                <input
                  type="text"
                  className="keyInput"
                  value={newKeyValue}
                  placeholder="Paste key value"
                  onChange={(e) => setNewKeyValue(e.target.value)}
                />
                <button
                  className="primaryBtn"
                  disabled={keysSaving || !newKeyName.trim() || !newKeyValue.trim()}
                  onClick={() => saveKey(newKeyName, newKeyValue)}
                >
                  Add Key
                </button>
              </div>
            </div>
            {keyFeedback && <div className="formHint">{keyFeedback}</div>}
            <div className="formActions">
              <button onClick={() => loadApiKeys()} disabled={keysLoading || keysSaving}>Refresh</button>
            </div>
          </div>

          <div className="settingsCard">
            <h2 className="settingsTitle">MCPs</h2>
            <div className="settingsHint">Changes take effect on the next agent session.</div>
            {mcpsLoading ? (
              <div className="formHint">Loading MCPs...</div>
            ) : (
              <div className="mcpList">
                {mcps.length === 0 && <div className="formHint">No MCPs available.</div>}
                {mcps.map((item) => (
                  <div key={item.mcp_name} className="mcpRow">
                    <div className="mcpMeta">
                      <div className="mcpName">{item.mcp_name}</div>
                      <div className="mcpStatus">{item.enabled ? "Enabled" : "Disabled"}</div>
                    </div>
                    <button
                      className={`primaryBtn ${item.enabled ? "disableBtn" : ""}`}
                      disabled={mcpsSaving}
                      onClick={() => toggleMcp(item.mcp_name, item.enabled)}
                    >
                      {item.enabled ? "Disable" : "Enable"}
                    </button>
                  </div>
                ))}
              </div>
            )}
            {mcpFeedback && <div className="formHint">{mcpFeedback}</div>}
            <div className="formActions">
              <button onClick={() => loadMcps()} disabled={mcpsLoading || mcpsSaving}>Refresh</button>
            </div>
          </div>
        </div>
      )}

      {bootstrapInput && (
        <div className="modalOverlay">
          <div className="modalContent" onClick={(e) => e.stopPropagation()}>
            <h2 className="modalTitle">{bootstrapInput.prompt}</h2>
            {bootstrapInput.method === "select" && (
              <div className="agentOptions">
                {bootstrapInput.options.map((opt) => (
                  <button
                    key={opt}
                    className="agentOption"
                    onClick={() => submitBootstrap(opt)}
                  >
                    {opt}
                  </button>
                ))}
              </div>
            )}

            {bootstrapInput.method === "confirm" && (
              <div className="formActions">
                <button className="primaryBtn" onClick={() => submitBootstrap(true)}>Yes</button>
                <button onClick={() => submitBootstrap(false)}>No</button>
              </div>
            )}

            {bootstrapInput.method === "text" && (
              <div className="formTextInputWrap">
                <input
                  type="text"
                  className="formTextInput"
                  value={bootstrapInput.textValue}
                  onChange={(e) =>
                    setBootstrapInput((prev) =>
                      prev ? { ...prev, textValue: e.target.value } : prev
                    )
                  }
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      submitBootstrap((bootstrapInput.textValue || "").trim());
                    }
                  }}
                  autoFocus
                />
                <div className="formActions">
                  <button className="primaryBtn" onClick={() => submitBootstrap((bootstrapInput.textValue || "").trim())}>
                    Submit
                  </button>
                  <button onClick={skipBootstrap}>Cancel</button>
                </div>
              </div>
            )}

            {bootstrapInput.method !== "text" && (
              <div className="formHint">Complete this prompt to continue.</div>
            )}
          </div>
        </div>
      )}

      {formUi && currentQuestion && (
        <div className="modalOverlay">
          <div className="modalContent modalContentWide" onClick={(e) => e.stopPropagation()}>
            <h2 className="modalTitle">{formUi.payload.title || formUi.payload.goal}</h2>
            <div className="formProgress">
              Question {Math.min(formUi.currentIndex + 1, visibleQuestions.length)}/{visibleQuestions.length}
            </div>

            <div className="formQuestion">{currentQuestion.question}</div>
            {currentQuestion.hint && <div className="formHint">{currentQuestion.hint}</div>}

            <div className="formAnswerBlock">
              {currentQuestion.type === "yesno" && (
                <div className="formActions">
                  <button
                    className={`agentOption ${formUi.answers[currentQuestion.id] === true ? "selectedOption" : ""}`}
                    onClick={() =>
                      setFormUi((prev) =>
                        prev
                          ? { ...prev, answers: { ...prev.answers, [currentQuestion.id]: true } }
                          : prev
                      )
                    }
                  >
                    Yes
                  </button>
                  <button
                    className={`agentOption ${formUi.answers[currentQuestion.id] === false ? "selectedOption" : ""}`}
                    onClick={() =>
                      setFormUi((prev) =>
                        prev
                          ? { ...prev, answers: { ...prev.answers, [currentQuestion.id]: false } }
                          : prev
                      )
                    }
                  >
                    No
                  </button>
                </div>
              )}

              {currentQuestion.type === "choice" && (
                <div className="agentOptions">
                  {currentOptions.map((opt, i) => (
                    <button
                      key={opt}
                      className={`agentOption ${formUi.selectIndex === i ? "selectedOption" : ""}`}
                      onClick={() => setFormUi((prev) => (prev ? { ...prev, selectIndex: i } : prev))}
                    >
                      {opt}
                    </button>
                  ))}
                  {currentOptions[formUi.selectIndex] === OTHER_OPTION && (
                    <input
                      type="text"
                      className="formTextInput"
                      value={formUi.otherValue}
                      placeholder={currentQuestion.placeholder || "Type your answer"}
                      onChange={(e) =>
                        setFormUi((prev) => (prev ? { ...prev, otherValue: e.target.value } : prev))
                      }
                    />
                  )}
                </div>
              )}

              {currentQuestion.type === "multiselect" && (
                <div className="agentOptions">
                  {currentOptions.map((opt, i) => {
                    const checked = formUi.multiselect.includes(i);
                    return (
                      <button
                        key={opt}
                        className={`agentOption ${checked ? "selectedOption" : ""}`}
                        onClick={() => toggleMultiselect(i)}
                      >
                        {checked ? "[✓] " : "[ ] "}
                        {opt}
                      </button>
                    );
                  })}
                  {formUi.multiselect.some((i) => currentOptions[i] === OTHER_OPTION) && (
                    <input
                      type="text"
                      className="formTextInput"
                      value={formUi.otherValue}
                      placeholder="Type custom option"
                      onChange={(e) =>
                        setFormUi((prev) => (prev ? { ...prev, otherValue: e.target.value } : prev))
                      }
                    />
                  )}
                </div>
              )}

              {currentQuestion.type === "text" && (
                <textarea
                  className="formTextarea"
                  value={formUi.textValue}
                  placeholder={currentQuestion.placeholder || "Type your answer"}
                  onChange={(e) =>
                    setFormUi((prev) => (prev ? { ...prev, textValue: e.target.value } : prev))
                  }
                />
              )}
            </div>

            <div className="formActions">
              <button onClick={goFormBack} disabled={formUi.currentIndex <= 0}>Back</button>
              {formUi.payload.allow_skip && (
                <button onClick={() => submitCollaborative({}, true)}>Skip</button>
              )}
              <button className="primaryBtn" onClick={advanceForm}>
                {formUi.currentIndex >= Math.max(0, visibleQuestions.length - 1) ? "Submit" : "Next"}
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
