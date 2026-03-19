(function registerChatView(global) {
  const components = global.ProxiComponents || (global.ProxiComponents = {});

  components.ChatView = function ChatView(props) {
    const {
      chatRef,
      messages,
      streaming,
      renderMarkdown,
      bootInfo,
      input,
      setInput,
      onKeyDown,
      hasSelectedAgent,
      canInteract,
      isListening,
      onMicClick,
      onSend,
      onAbort,
    } = props;

    return (
      <>
        <div className="chat" ref={chatRef}>
          {messages.map((m, i) => {
            const displayRole = m.role === "assistant" ? "proxi" : m.role;
            const isMarkdown = m.role === "assistant";
            return (
              <div key={i} className={`msg ${m.role}`}>
                <span className="role">{displayRole}</span>
                {isMarkdown ? (
                  <span
                    className="content md"
                    dangerouslySetInnerHTML={{ __html: renderMarkdown(m.content) }}
                  />
                ) : (
                  <span className="content">{m.content}</span>
                )}
              </div>
            );
          })}

          {streaming && (
            <div className="msg assistant">
              <span className="role">proxi</span>
              <span
                className="content md"
                dangerouslySetInnerHTML={{ __html: renderMarkdown(streaming) }}
              />
            </div>
          )}
        </div>

        <div className="footer-wrapper">
          <div className="footer">
            {bootInfo && (
              <div className="bootInfo">
                Agent: <strong>{bootInfo.agentId}</strong> - Session:{" "}
                <strong>{bootInfo.sessionId.slice(0, 8)}</strong>
              </div>
            )}
            <div className="inputRow">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onKeyDown}
                placeholder={
                  hasSelectedAgent
                    ? "Ask anything or click mic to speak..."
                    : "Select an agent first..."
                }
                disabled={!canInteract}
              />
              <button
                className={`micBtn ${isListening ? "listening" : ""}`}
                onClick={onMicClick}
                disabled={!canInteract}
                title="Click to start/stop listening"
              >
                {isListening ? "Stop" : "Mic"}
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
    );
  };
})(window);
