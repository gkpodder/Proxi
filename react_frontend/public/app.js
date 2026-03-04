const { useEffect, useMemo, useRef, useState } = React;

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
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

function App() {
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

      <div className="chat" ref={chatRef}>
        {messages.map((m, i) => {
          const displayRole = m.role === "assistant" ? "proxi" : m.role;
          return (
            <div key={i} className={`msg ${m.role}`}>
              <span className="role">{displayRole}</span>
              <span className="content">{m.content}</span>
            </div>
          );
        })}
        {streaming && (
          <div className="msg assistant">
            <span className="role">proxi</span>
            <span className="content">{streaming}</span>
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
