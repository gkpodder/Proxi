const { useEffect, useMemo, useRef, useState } = React;

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

function App() {
  const [socketState, setSocketState] = useState("connecting");
  const [statusLabel, setStatusLabel] = useState("Starting...");
  const [messages, setMessages] = useState([]);
  const [streaming, setStreaming] = useState("");
  const [input, setInput] = useState("");
  const [bootInfo, setBootInfo] = useState(null);
  const [agentModal, setAgentModal] = useState(null);
  const [isListening, setIsListening] = useState(false);
  const [darkMode, setDarkMode] = useState(true);

  const wsRef = useRef(null);
  const chatRef = useRef(null);
  const recognizerRef = useRef(null);

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
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      addError("Bridge is not connected.");
      return;
    }
    wsRef.current.send(JSON.stringify({ type: "switch_agent" }));
    commitStream();
    addSystem("Switching agent...");
    setStatusLabel("Switching...");
    setBootInfo(null);
  }

  function handleMessage(msg) {
    switch (msg.type) {
      case "ready":
        setStatusLabel("Bridge ready");
        addSystem("Bridge ready.");
        break;
      case "boot_complete":
        setBootInfo({ agentId: msg.agentId, sessionId: msg.sessionId });
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
    const method = msg.method || "text";
    const prompt = msg.prompt || "Input required";

    if (method === "confirm") {
      const value = window.confirm(prompt);
      send({ type: "user_input", value });
      return;
    }

    if (method === "select") {
      const options = Array.isArray(msg.options) ? msg.options : [];
      setAgentModal({
        prompt,
        options,
        onSelect: (value) => {
          send({ type: "user_input", value });
          setAgentModal(null);
        },
      });
      return;
    }

    const value = window.prompt(prompt);
    send({ type: "user_input", value: value == null ? false : value });
  }

  function onSend() {
    const task = input.trim();
    if (!task) return;
    addUser(task);
    setInput("");
    setStatusLabel("Running...");
    setStreaming("");
    send({ type: "start", task });
  }

  function onAbort() {
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
            disabled={socketState !== "connected"}
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
              placeholder="Ask anything or click 🎤 to speak..."
            />
            <button
              className={`micBtn ${isListening ? "listening" : ""}`}
              onClick={onMicClick}
              disabled={socketState !== "connected"}
              title="Click to start/stop listening"
            >
              {isListening ? "⏹️" : "🎤"}
            </button>
            <button onClick={onSend} disabled={socketState !== "connected"}>
              Send
            </button>
            <button onClick={onAbort} disabled={socketState !== "connected"}>
              Abort
            </button>
          </div>
        </div>
      </div>

      {agentModal && (
        <div className="modalOverlay" onClick={() => setAgentModal(null)}>
          <div className="modalContent" onClick={(e) => e.stopPropagation()}>
            <h2 className="modalTitle">{agentModal.prompt}</h2>
            <div className="agentOptions">
              {agentModal.options.map((opt) => (
                <button
                  key={opt}
                  className="agentOption"
                  onClick={() => agentModal.onSelect(opt)}
                >
                  {opt}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
