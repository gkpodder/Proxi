(function registerSettingsModal(global) {
  const { useEffect, useMemo, useRef, useState } = React;
  const components = global.ProxiComponents || (global.ProxiComponents = {});
  const { TIMEZONE_OPTIONS } = global.ProxiUtils;

  function Section({ sectionKey, title, openSections, toggleSection, children, sectionRefs }) {
    return (
      <section
        className="settingsSection"
        ref={(el) => {
          sectionRefs.current[sectionKey] = el;
        }}
      >
        <button className="settingsSectionHeader" onClick={() => toggleSection(sectionKey)}>
          <span>{title}</span>
          <span className={`chevron ${openSections[sectionKey] ? "open" : ""}`}>v</span>
        </button>
        {openSections[sectionKey] && <div className="settingsSectionBody">{children}</div>}
      </section>
    );
  }

  components.SettingsModal = function SettingsModal(props) {
    const {
      isOpen,
      onClose,
      bootInfo,
      socketState,
      isPromptActive,
      onSwitchAgent,
      selectedAgentId,
      setSelectedAgentId,
      agentFeedback,
      switchAgentToSelected,
      profile,
      profileLoading,
      profileSaving,
      profileFeedback,
      updateProfileField,
      saveUserProfile,
      clearUserProfile,
      loadUserProfile,
      keysLoading,
      keysSaving,
      keyFeedback,
      apiKeys,
      keyDrafts,
      setKeyDrafts,
      newKeyName,
      setNewKeyName,
      newKeyValue,
      setNewKeyValue,
      saveKey,
      loadApiKeys,
      integrationsLoading,
      integrationsSaving,
      integrationFeedback,
      integrations,
      toggleIntegration,
      loadIntegrations,
      cronJobs,
      cronLoading,
      cronSaving,
      cronFeedback,
      cronSupportsSixField,
      availableAgents,
      cronDraft,
      setCronDraft,
      saveCronJob,
      removeCronJob,
      setCronJobPaused,
      loadCronJobs,
      editCronJob,
      clearCronDraft,
      llmProvider,
      llmModel,
      llmProviders,
      llmModelsByProvider,
      llmLoading,
      llmSaving,
      llmFeedback,
      changeLlmProvider,
      setLlmModel,
      saveLlmConfig,
      loadLlmConfig,
      generaFeedback,
      generaBusy,
      generaReasoningEffort,
      runCompactCommand,
      runReasoningEffortCommand,
      clearSessionHistory,
      webhooks,
      webhookLoading,
      webhookSaving,
      webhookFeedback,
      webhookDraft,
      setWebhookDraft,
      saveWebhook,
      removeWebhook,
      setWebhookPaused,
      loadWebhooks,
      editWebhook,
      clearWebhookDraft,
    } = props;

    const [openSections, setOpenSections] = useState({
      genera: true,
      agent: true,
      profile: true,
      keys: false,
      integrations: false,
      cron: false,
      webhooks: false,
    });
    const [compactHint, setCompactHint] = useState("");
    const [selectedReasoningEffort, setSelectedReasoningEffort] = useState("minimal");
    const [scheduleMode, setScheduleMode] = useState("quick");
    const [everyValue, setEveryValue] = useState("30");
    const [everyUnit, setEveryUnit] = useState("minute");
    const [editingCron, setEditingCron] = useState(false);

    const sectionRefs = useRef({});

    const sectionItems = useMemo(
      () => [
        { key: "genera", label: "General" },
        { key: "agent", label: "Agent" },
        { key: "profile", label: "Profile" },
        { key: "keys", label: "API Keys" },
        { key: "integrations", label: "Integrations" },
        { key: "cron", label: "Cron Jobs" },
        { key: "webhooks", label: "Webhooks" },
      ],
      []
    );

    useEffect(() => {
      const normalized = String(generaReasoningEffort || "minimal").trim().toLowerCase();
      const valid = ["minimal", "low", "medium", "high"];
      setSelectedReasoningEffort(valid.includes(normalized) ? normalized : "minimal");
    }, [generaReasoningEffort]);

    useEffect(() => {
      if (scheduleMode !== "quick") return;
      const generated = buildQuickCron();
      setCronDraft((prev) => ({ ...prev, schedule: generated }));
    }, [scheduleMode, everyValue, everyUnit, setCronDraft]);

    useEffect(() => {
      if (!Array.isArray(availableAgents) || availableAgents.length === 0) return;
      if (cronDraft.targetAgent) return;
      setCronDraft((prev) => ({ ...prev, targetAgent: availableAgents[0] }));
    }, [availableAgents, cronDraft.targetAgent, setCronDraft]);

    useEffect(() => {
      if (!Array.isArray(availableAgents) || availableAgents.length === 0) return;
      if (webhookDraft.targetAgent) return;
      setWebhookDraft((prev) => ({ ...prev, targetAgent: availableAgents[0] }));
    }, [availableAgents, webhookDraft.targetAgent, setWebhookDraft]);

    if (!isOpen) return null;

    function toggleSection(sectionKey) {
      setOpenSections((prev) => ({ ...prev, [sectionKey]: !prev[sectionKey] }));
    }

    function jumpToSection(sectionKey) {
      setOpenSections((prev) => ({ ...prev, [sectionKey]: true }));
      requestAnimationFrame(() => {
        sectionRefs.current[sectionKey]?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }

    function buildQuickCron() {
      const rawValue = Number.parseInt(String(everyValue || "1"), 10);
      const n = Number.isFinite(rawValue) ? Math.max(1, rawValue) : 1;

      if (everyUnit === "second") {
        // 6-field format: second minute hour day month day_of_week
        return `*/${n} * * * * *`;
      }
      if (everyUnit === "minute") {
        return `*/${n} * * * *`;
      }
      if (everyUnit === "day") {
        return `0 0 */${n} * *`;
      }
      if (everyUnit === "week") {
        return `0 0 */${Math.max(1, n * 7)} * *`;
      }
      if (everyUnit === "monthly") {
        return `0 0 1 */${n} *`;
      }
      return "*/30 * * * *";
    }

    return (
      <div className="settingsOverlay" onClick={onClose}>
        <div className="settingsPopup" onClick={(e) => e.stopPropagation()}>
          <div className="settingsModalHeader">
            <h2>Settings</h2>
            <button className="settingsCloseBtn" onClick={onClose} aria-label="Close settings">
              x
            </button>
          </div>

          <div className="settingsLayout">
            <aside className="settingsSidebar">
              {sectionItems.map((item) => (
                <button key={item.key} onClick={() => jumpToSection(item.key)}>
                  {item.label}
                </button>
              ))}
            </aside>

            <div className="settingsContent">
              <Section
                sectionKey="genera"
                title="General"
                openSections={openSections}
                toggleSection={toggleSection}
                sectionRefs={sectionRefs}
              >
                <div className="settingsHint">Fast controls for context clearing, reasoning depth, compaction, and active LLM selection.</div>

                <div className="formActions">
                  <button
                    className="primaryBtn"
                    onClick={clearSessionHistory}
                    disabled={generaBusy}
                  >
                    Clear History
                  </button>
                </div>

                <div className="profileGrid">
                  <label className="profileField">
                    <span>Reasoning Effort</span>
                    <select
                      className="profileSelect"
                      value={selectedReasoningEffort}
                      disabled={generaBusy}
                      onChange={(e) => setSelectedReasoningEffort(e.target.value)}
                    >
                      <option value="minimal">minimal</option>
                      <option value="low">low</option>
                      <option value="medium">medium</option>
                      <option value="high">high</option>
                    </select>
                  </label>
                  <div style={{ display: "flex", flexDirection: "column", gap: "6px", justifyContent: "flex-end" }}>
                    <button
                      className="primaryBtn"
                      onClick={() => runReasoningEffortCommand(selectedReasoningEffort)}
                      disabled={
                        generaBusy ||
                        String(selectedReasoningEffort || "").trim().toLowerCase() ===
                          String(generaReasoningEffort || "").trim().toLowerCase()
                      }
                    >
                      Switch Reasoning
                    </button>
                  </div>
                </div>

                <div className="profileGrid">
                  <label className="profileField profileFieldFull">
                    <span>Compact Focus Hint (optional)</span>
                    <input
                      type="text"
                      value={compactHint}
                      disabled={generaBusy}
                      placeholder="Optional focus, e.g. summarize only unresolved tasks"
                      onChange={(e) => setCompactHint(e.target.value)}
                    />
                  </label>
                </div>
                <div className="formActions generaCommandActions">
                  <button
                    className="primaryBtn"
                    onClick={() => runCompactCommand(compactHint)}
                    disabled={generaBusy}
                  >
                    Compact
                  </button>
                  <button
                    onClick={() => setCompactHint("")}
                    disabled={generaBusy || !compactHint.trim()}
                  >
                    Clear Focus Hint
                  </button>
                </div>

                <div className="settingsHint">Choose the provider and model used for all new turns.</div>
                <div className="profileGrid">
                  <label className="profileField">
                    <span>Provider</span>
                    <select
                      className="profileSelect"
                      value={llmProvider}
                      disabled={llmLoading || llmSaving || generaBusy}
                      onChange={(e) => changeLlmProvider(e.target.value)}
                    >
                      {(llmProviders || []).map((provider) => (
                        <option key={provider} value={provider}>
                          {provider}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="profileField">
                    <span>Model</span>
                    <select
                      className="profileSelect"
                      value={llmModel}
                      disabled={llmLoading || llmSaving || generaBusy}
                      onChange={(e) => setLlmModel(e.target.value)}
                    >
                      {((llmModelsByProvider && llmModelsByProvider[llmProvider]) || []).map((modelName) => (
                        <option key={modelName} value={modelName}>
                          {modelName}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <div className="formActions">
                  <button
                    className="primaryBtn"
                    onClick={saveLlmConfig}
                    disabled={
                      llmLoading ||
                      llmSaving ||
                      generaBusy ||
                      ((llmProvider === bootInfo?.llm_provider) && (llmModel === bootInfo?.llm_model))
                    }
                  >
                    {((llmProvider !== bootInfo?.llm_provider) || (llmModel !== bootInfo?.llm_model)) ? "Switch LLM Provider" : "LLM Provider Selected"}
                  </button>
                  <button onClick={() => loadLlmConfig()} disabled={llmLoading || llmSaving || generaBusy}>
                    Refresh
                  </button>
                </div>

                {(generaFeedback || llmFeedback) && <div className="formHint">{generaFeedback || llmFeedback}</div>}
              </Section>

              <Section
                sectionKey="agent"
                title="Agent"
                openSections={openSections}
                toggleSection={toggleSection}
                sectionRefs={sectionRefs}
              >
                <div className="settingsHint">Switch agents between tasks.</div>
                <div className="settingsRow">
                  <div>
                    <div className="settingsLabel">Current agent</div>
                    <div className="settingsValue">{bootInfo?.agentId || "Not selected"}</div>
                  </div>
                  <select
                    className="profileSelect"
                    value={selectedAgentId}
                    disabled={socketState !== "connected" || isPromptActive || availableAgents.length === 0}
                    onChange={(e) => setSelectedAgentId(e.target.value)}
                  >
                    {availableAgents.length === 0 ? (
                      <option value="">No agents found</option>
                    ) : (
                      availableAgents.map((agentId) => (
                        <option key={agentId} value={agentId}>
                          {agentId}
                        </option>
                      ))
                    )}
                  </select>
                  <button
                    className="primaryBtn"
                    onClick={switchAgentToSelected || onSwitchAgent}
                    disabled={
                      socketState !== "connected" ||
                      isPromptActive ||
                      !selectedAgentId ||
                      selectedAgentId === bootInfo?.agentId
                    }
                  >
                    {selectedAgentId !== bootInfo?.agentId ? "Switch Agent" : "Agent Selected"}
                  </button>
                </div>
                {agentFeedback && <div className="formHint">{agentFeedback}</div>}
              </Section>

              <Section
                sectionKey="profile"
                title="Profile"
                openSections={openSections}
                toggleSection={toggleSection}
                sectionRefs={sectionRefs}
              >
                <div className="settingsHint">
                  Used to personalize replies like email signatures and timezone-aware suggestions.
                </div>
                <div className="settingsHint">
                  Deleting profile data applies on the next session; current context may still contain earlier values.
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
                          <option key={tz} value={tz}>
                            {tz}
                          </option>
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
                        placeholder="Share context for Proxi (optional)."
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
              </Section>

              <Section
                sectionKey="keys"
                title="API Keys"
                openSections={openSections}
                toggleSection={toggleSection}
                sectionRefs={sectionRefs}
              >
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
                  <button onClick={() => loadApiKeys()} disabled={keysLoading || keysSaving}>
                    Refresh
                  </button>
                </div>
              </Section>

              <Section
                sectionKey="integrations"
                title="Integrations"
                openSections={openSections}
                toggleSection={toggleSection}
                sectionRefs={sectionRefs}
              >
                <div className="settingsHint">Changes take effect on the next agent session.</div>
                {integrationsLoading ? (
                  <div className="formHint">Loading integrations...</div>
                ) : (
                  <div className="mcpList">
                    {integrations.length === 0 && <div className="formHint">No integrations available.</div>}
                    {integrations.map((item) => (
                      <div key={item.integration_name} className="mcpRow">
                        <div className="mcpMeta">
                          <div className="mcpName">{item.integration_name}</div>
                          <div className="mcpStatus">{item.enabled ? "Enabled" : "Disabled"}</div>
                        </div>
                        <button
                          className={`primaryBtn ${item.enabled ? "disableBtn" : ""}`}
                          disabled={integrationsSaving}
                          onClick={() => toggleIntegration(item.integration_name, item.enabled)}
                        >
                          {item.enabled ? "Disable" : "Enable"}
                        </button>
                      </div>
                    ))}
                  </div>
                )}

                {integrationFeedback && <div className="formHint">{integrationFeedback}</div>}
                <div className="formActions">
                  <button onClick={() => loadIntegrations()} disabled={integrationsLoading || integrationsSaving}>
                    Refresh
                  </button>
                </div>
              </Section>

              <Section
                sectionKey="cron"
                title="Cron Jobs"
                openSections={openSections}
                toggleSection={toggleSection}
                sectionRefs={sectionRefs}
              >
                <div className="settingsHint">
                  Configure scheduled prompts that run through the gateway and persist in `~/.proxi/gateway.yml`.
                </div>

                {cronLoading ? (
                  <div className="formHint">Loading cron jobs...</div>
                ) : (
                  <div className="mcpList">
                    {cronJobs.length === 0 && <div className="formHint">No cron jobs configured.</div>}
                    {cronJobs.map((item) => (
                      <div key={item.source_id} className="mcpRow">
                        <div className="mcpMeta">
                          <div className="mcpName">{item.source_id}</div>
                          <div className="mcpStatus">
                            {item.schedule} → {item.target_agent} | p{item.priority} | {item.paused ? "Paused" : "Running"}
                          </div>
                        </div>
                        <div className="formActions">
                          <button onClick={() => editCronJob(item)} disabled={cronSaving}>Edit</button>
                          <button
                            onClick={() => setCronJobPaused(item.source_id, !item.paused)}
                            disabled={cronSaving}
                          >
                            {item.paused ? "Resume" : "Pause"}
                          </button>
                          <button className="disableBtn" onClick={() => removeCronJob(item.source_id)} disabled={cronSaving}>
                            Delete
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                <div className="keyAddSection">
                  <div className="keyAddTitle">Create or Update Cron Job</div>
                  <div className="settingsHint">
                    Easy Schedule is the default. Switch to Custom Cron only if you want to type cron manually.
                  </div>

                  <div className="profileGrid">
                    <label className="profileField">
                      <span>Source ID</span>
                      <input
                        type="text"
                        value={cronDraft.sourceId}
                        placeholder="cron_daily_summary"
                        onChange={(e) => setCronDraft((prev) => ({ ...prev, sourceId: e.target.value }))}
                      />
                    </label>
                    <label className="profileField">
                      <span>Target Agent</span>
                      <select
                        className="profileSelect"
                        value={cronDraft.targetAgent}
                        disabled={availableAgents.length === 0}
                        onChange={(e) => setCronDraft((prev) => ({ ...prev, targetAgent: e.target.value }))}
                      >
                        {availableAgents.length === 0 ? (
                          <option value="">No agents found</option>
                        ) : (
                          availableAgents.map((agentId) => (
                            <option key={agentId} value={agentId}>
                              {agentId}
                            </option>
                          ))
                        )}
                      </select>
                    </label>
                  </div>

                  <div className="profileGrid">
                    <label className="profileField">
                      <span>Target Session (optional)</span>
                      <input
                        type="text"
                        value={cronDraft.targetSession}
                        placeholder="main"
                        onChange={(e) => setCronDraft((prev) => ({ ...prev, targetSession: e.target.value }))}
                      />
                    </label>
                    <label className="profileField">
                      <span>Priority</span>
                      <select
                        className="profileSelect"
                        value={cronDraft.priority}
                        onChange={(e) => setCronDraft((prev) => ({ ...prev, priority: e.target.value }))}
                      >
                        <option value="0">0</option>
                        <option value="1">1</option>
                        <option value="2">2</option>
                        <option value="3">3</option>
                        <option value="4">4</option>
                        <option value="5">5</option>
                      </select>
                    </label>
                  </div>

                  {scheduleMode === "quick" && (
                    <div className="profileGrid">
                      <label className="profileField">
                        <span>Every</span>
                        <input
                          type="number"
                          min="1"
                          step="1"
                          value={everyValue}
                          onChange={(e) => setEveryValue(e.target.value)}
                        />
                      </label>
                      <label className="profileField">
                        <span>Unit</span>
                        <select
                          className="profileSelect"
                          value={everyUnit}
                          onChange={(e) => setEveryUnit(e.target.value)}
                        >
                          <option value="second" disabled={!cronSupportsSixField}>Second</option>
                          <option value="minute">Minute</option>
                          <option value="day">Day</option>
                          <option value="week">Week</option>
                          <option value="monthly">Monthly</option>
                        </select>
                      </label>
                    </div>
                  )}

                  <div className="profileGrid">
                    <label className="profileField profileFieldFull">
                      <span>Generated Cron {editingCron && "(editing)"}</span>
                      {!editingCron && scheduleMode === "quick" && (
                        <div
                          onClick={() => setEditingCron(true)}
                          style={{
                            cursor: "pointer",
                            background: "#1a1a1a",
                            border: "1px solid #333",
                            color: "#e5e5e5",
                            borderRadius: "6px",
                            padding: "10px 12px",
                            fontSize: "14px",
                            userSelect: "none",
                            transition: "all 0.2s",
                          }}
                          onMouseEnter={(e) => {
                            e.target.style.borderColor = "#3b82f6";
                            e.target.style.background = "#252525";
                          }}
                          onMouseLeave={(e) => {
                            e.target.style.borderColor = "#333";
                            e.target.style.background = "#1a1a1a";
                          }}
                        >
                          {buildQuickCron()}
                        </div>
                      )}
                      {editingCron || scheduleMode === "manual" ? (
                        <input
                          type="text"
                          autoFocus={editingCron}
                          value={cronDraft.schedule}
                          placeholder="0 8 * * MON-FRI"
                          onChange={(e) => setCronDraft((prev) => ({ ...prev, schedule: e.target.value }))}
                          onBlur={() => setEditingCron(false)}
                          onKeyDown={(e) => {
                            if (e.key === "Escape") {
                              setEditingCron(false);
                            }
                          }}
                        />
                      ) : null}
                      <div className="formHint">Example formats: */30 * * * * or 0 8 * * MON-FRI | Click to edit</div>
                    </label>
                  </div>

                  <div className="profileGrid">
                    <label className="profileField">
                      <span>State</span>
                      <select
                        className="profileSelect"
                        value={cronDraft.paused ? "paused" : "running"}
                        onChange={(e) =>
                          setCronDraft((prev) => ({
                            ...prev,
                            paused: e.target.value === "paused",
                          }))
                        }
                      >
                        <option value="running">Running</option>
                        <option value="paused">Paused</option>
                      </select>
                    </label>
                  </div>

                  <div className="profileGrid">
                    <label className="profileField profileFieldFull">
                      <span>Prompt</span>
                      <textarea
                        className="formTextarea"
                        value={cronDraft.prompt}
                        placeholder="Summarize yesterday's work and plan today."
                        onChange={(e) => setCronDraft((prev) => ({ ...prev, prompt: e.target.value }))}
                      />
                    </label>
                  </div>
                </div>

                {cronFeedback && <div className="formHint">{cronFeedback}</div>}
                <div className="formActions">
                  <button className="primaryBtn" onClick={saveCronJob} disabled={cronLoading || cronSaving}>
                    Save Cron Job
                  </button>
                  <button onClick={clearCronDraft} disabled={cronLoading || cronSaving}>
                    Clear Form
                  </button>
                  <button onClick={() => loadCronJobs()} disabled={cronLoading || cronSaving}>
                    Refresh
                  </button>
                </div>
              </Section>

              <Section
                sectionKey="webhooks"
                title="Webhooks"
                openSections={openSections}
                toggleSection={toggleSection}
                sectionRefs={sectionRefs}
              >
                <div className="settingsHint">
                  Configure inbound webhook sources for external integrations at /channels/webhook/{"{source_id}"}.
                </div>

                {webhookLoading ? (
                  <div className="formHint">Loading webhooks...</div>
                ) : (
                  <div className="mcpList">
                    {webhooks.length === 0 && <div className="formHint">No webhook sources configured.</div>}
                    {webhooks.map((item) => (
                      <div key={item.source_id} className="mcpRow">
                        <div className="mcpMeta">
                          <div className="mcpName">{item.source_id}</div>
                          <div className="mcpStatus">
                            {item.target_agent} | p{item.priority} | {item.paused ? "Paused" : "Running"}
                            {item.has_secret ? " | Signed" : " | Unsigned"}
                          </div>
                        </div>
                        <div className="formActions">
                          <button onClick={() => editWebhook(item)} disabled={webhookSaving}>Edit</button>
                          <button onClick={() => setWebhookPaused(item.source_id, !item.paused)} disabled={webhookSaving}>
                            {item.paused ? "Resume" : "Pause"}
                          </button>
                          <button className="disableBtn" onClick={() => removeWebhook(item.source_id)} disabled={webhookSaving}>
                            Delete
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                <div className="keyAddSection">
                  <div className="keyAddTitle">Create or Update Webhook Source</div>
                  <div className="profileGrid">
                    <label className="profileField">
                      <span>Source ID</span>
                      <input
                        type="text"
                        value={webhookDraft.sourceId}
                        placeholder="github_push"
                        onChange={(e) => setWebhookDraft((prev) => ({ ...prev, sourceId: e.target.value }))}
                      />
                    </label>
                    <label className="profileField">
                      <span>Target Agent</span>
                      <select
                        className="profileSelect"
                        value={webhookDraft.targetAgent}
                        disabled={availableAgents.length === 0}
                        onChange={(e) => setWebhookDraft((prev) => ({ ...prev, targetAgent: e.target.value }))}
                      >
                        {availableAgents.length === 0 ? (
                          <option value="">No agents found</option>
                        ) : (
                          availableAgents.map((agentId) => (
                            <option key={agentId} value={agentId}>
                              {agentId}
                            </option>
                          ))
                        )}
                      </select>
                    </label>
                  </div>

                  <div className="profileGrid">
                    <label className="profileField">
                      <span>Target Session (optional)</span>
                      <input
                        type="text"
                        value={webhookDraft.targetSession}
                        placeholder="main"
                        onChange={(e) => setWebhookDraft((prev) => ({ ...prev, targetSession: e.target.value }))}
                      />
                    </label>
                    <label className="profileField">
                      <span>Priority</span>
                      <select
                        className="profileSelect"
                        value={webhookDraft.priority}
                        onChange={(e) => setWebhookDraft((prev) => ({ ...prev, priority: e.target.value }))}
                      >
                        <option value="0">0</option>
                        <option value="1">1</option>
                        <option value="2">2</option>
                        <option value="3">3</option>
                        <option value="4">4</option>
                        <option value="5">5</option>
                      </select>
                    </label>
                  </div>

                  <div className="profileGrid">
                    <label className="profileField profileFieldFull">
                      <span>Prompt Template (optional)</span>
                      <textarea
                        className="formTextarea"
                        value={webhookDraft.promptTemplate}
                        placeholder="Repo {{repository.name}} received a {{action}} event"
                        onChange={(e) => setWebhookDraft((prev) => ({ ...prev, promptTemplate: e.target.value }))}
                      />
                    </label>
                  </div>

                  <div className="profileGrid">
                    <label className="profileField">
                      <span>HMAC Secret Env (optional)</span>
                      <input
                        type="text"
                        value={webhookDraft.secretEnv}
                        placeholder="GITHUB_WEBHOOK_SECRET"
                        onChange={(e) => setWebhookDraft((prev) => ({ ...prev, secretEnv: e.target.value }))}
                      />
                    </label>
                    <label className="profileField">
                      <span>State</span>
                      <select
                        className="profileSelect"
                        value={webhookDraft.paused ? "paused" : "running"}
                        onChange={(e) =>
                          setWebhookDraft((prev) => ({
                            ...prev,
                            paused: e.target.value === "paused",
                          }))
                        }
                      >
                        <option value="running">Running</option>
                        <option value="paused">Paused</option>
                      </select>
                    </label>
                  </div>
                </div>

                {webhookFeedback && <div className="formHint">{webhookFeedback}</div>}
                <div className="formActions">
                  <button className="primaryBtn" onClick={saveWebhook} disabled={webhookLoading || webhookSaving}>
                    Save Webhook
                  </button>
                  <button onClick={clearWebhookDraft} disabled={webhookLoading || webhookSaving}>
                    Clear Form
                  </button>
                  <button onClick={() => loadWebhooks()} disabled={webhookLoading || webhookSaving}>
                    Refresh
                  </button>
                </div>
              </Section>

            </div>
          </div>
        </div>
      </div>
    );
  };
})(window);
