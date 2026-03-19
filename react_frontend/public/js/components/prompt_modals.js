(function registerPromptModals(global) {
  const components = global.ProxiComponents || (global.ProxiComponents = {});
  const { OTHER_OPTION } = global.ProxiUtils;

  components.BootstrapModal = function BootstrapModal({ bootstrapInput, setBootstrapInput, submitBootstrap, skipBootstrap }) {
    if (!bootstrapInput) return null;

    return (
      <div className="modalOverlay">
        <div className="modalContent" onClick={(e) => e.stopPropagation()}>
          <h2 className="modalTitle">{bootstrapInput.prompt}</h2>
          {bootstrapInput.method === "select" && (
            <div className="agentOptions">
              {bootstrapInput.options.map((opt) => (
                <button key={opt} className="agentOption" onClick={() => submitBootstrap(opt)}>
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
                  setBootstrapInput((prev) => (prev ? { ...prev, textValue: e.target.value } : prev))
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
    );
  };

  components.CollaborativeFormModal = function CollaborativeFormModal(props) {
    const {
      formUi,
      currentQuestion,
      visibleQuestions,
      currentOptions,
      setFormUi,
      toggleMultiselect,
      goFormBack,
      submitCollaborative,
      advanceForm,
    } = props;

    if (!formUi || !currentQuestion) return null;

    return (
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
                      prev ? { ...prev, answers: { ...prev.answers, [currentQuestion.id]: true } } : prev
                    )
                  }
                >
                  Yes
                </button>
                <button
                  className={`agentOption ${formUi.answers[currentQuestion.id] === false ? "selectedOption" : ""}`}
                  onClick={() =>
                    setFormUi((prev) =>
                      prev ? { ...prev, answers: { ...prev.answers, [currentQuestion.id]: false } } : prev
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
                      {checked ? "[x] " : "[ ] "}
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
            {formUi.payload.allow_skip && <button onClick={() => submitCollaborative({}, true)}>Skip</button>}
            <button className="primaryBtn" onClick={advanceForm}>
              {formUi.currentIndex >= Math.max(0, visibleQuestions.length - 1) ? "Submit" : "Next"}
            </button>
          </div>
        </div>
      </div>
    );
  };
})(window);
