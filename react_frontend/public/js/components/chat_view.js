(function registerChatView(global) {
  const components = global.ProxiComponents || (global.ProxiComponents = {});

  components.ChatView = function ChatView(props) {
    const {
      chatRef,
      messages,
      activityItems,
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
      <div className="mainPanels">
        <div className="panel panelLeft">
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
        </div>

        <aside className="panel panelRight activityPanel">
          <div className="activityHeader">Tool and MCP Activity</div>
          <div className="activityList">
            {activityItems.length === 0 && (
              <div className="activityEmpty">No activity yet. Tool calls and model thinking will appear here.</div>
            )}
            {activityItems.map((item) => (
              <div key={item.id} className={`activityItem ${item.kind}`}>
                <div className="activityMeta">
                  <span className="activityKind">{item.kind}</span>
                  <span className="activityAt">{item.at}</span>
                </div>
                <div className="activityTitle">{item.title}</div>
                {item.content && <div className="activityContent">{item.content}</div>}
              </div>
            ))}
          </div>
        </aside>
      </div>
    );
  };
})(window);
