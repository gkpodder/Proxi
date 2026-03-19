(function registerSettingsModal(global) {
  const { useMemo, useRef, useState } = React;
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
      mcpsLoading,
      mcpsSaving,
      mcpFeedback,
      mcps,
      toggleMcp,
      loadMcps,
    } = props;

    const [openSections, setOpenSections] = useState({
      agent: true,
      profile: true,
      keys: false,
      mcps: false,
    });

    const sectionRefs = useRef({});

    const sectionItems = useMemo(
      () => [
        { key: "agent", label: "Agent" },
        { key: "profile", label: "Profile" },
        { key: "keys", label: "API Keys" },
        { key: "mcps", label: "MCPs" },
      ],
      []
    );

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
                  <button
                    className="primaryBtn"
                    onClick={onSwitchAgent}
                    disabled={socketState !== "connected" || isPromptActive}
                  >
                    Switch Agent
                  </button>
                </div>
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
                sectionKey="mcps"
                title="MCPs"
                openSections={openSections}
                toggleSection={toggleSection}
                sectionRefs={sectionRefs}
              >
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
                  <button onClick={() => loadMcps()} disabled={mcpsLoading || mcpsSaving}>
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
