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
  const [activityCollapsed, setActivityCollapsed] = useState(false);
  const [streaming, setStreaming] = useState("");
  const [input, setInput] = useState("");
  const [bootInfo, setBootInfo] = useState(null);
  const [bootstrapInput, setBootstrapInput] = useState(null);
  const [formUi, setFormUi] = useState(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [wakeListening, setWakeListening] = useState(false);
  const [voiceEnabled, setVoiceEnabled] = useState(() => {
    try {
      return window.localStorage.getItem("proxi.voiceEnabled") === "true";
    } catch {
      return false;
    }
  });
  const [voiceSilenceSeconds, setVoiceSilenceSeconds] = useState(() => {
    try {
      const raw = Number.parseInt(window.localStorage.getItem("proxi.voiceSilenceSeconds") || "2", 10);
      if (Number.isFinite(raw)) return Math.max(1, Math.min(5, raw));
    } catch {
      // ignore storage errors
    }
    return 2;
  });
  const [voiceAutoSendAfterSilence, setVoiceAutoSendAfterSilence] = useState(() => {
    try {
      const stored = window.localStorage.getItem("proxi.voiceAutoSendAfterSilence");
      if (stored == null) return true;
      return stored === "true";
    } catch {
      return true;
    }
  });
  const [voiceBeepEnabled, setVoiceBeepEnabled] = useState(() => {
    try {
      const stored = window.localStorage.getItem("proxi.voiceBeepEnabled");
      if (stored == null) return true;
      return stored === "true";
    } catch {
      return true;
    }
  });
  const [ttsEnabled, setTtsEnabled] = useState(() => {
    try {
      const stored = window.localStorage.getItem("proxi.ttsEnabled");
      if (stored == null) return false;
      return stored === "true";
    } catch {
      return false;
    }
  });
  const [ttsVoiceName, setTtsVoiceName] = useState(() => {
    try {
      return window.localStorage.getItem("proxi.ttsVoiceName") || "";
    } catch {
      return "";
    }
  });
  const [ttsVoiceUri, setTtsVoiceUri] = useState(() => {
    try {
      return window.localStorage.getItem("proxi.ttsVoiceUri") || "";
    } catch {
      return "";
    }
  });
  const [ttsRate, setTtsRate] = useState(() => {
    try {
      const raw = Number.parseFloat(window.localStorage.getItem("proxi.ttsRate") || "1");
      if (Number.isFinite(raw)) return Math.max(0.5, Math.min(2, raw));
    } catch {
      // ignore storage errors
    }
    return 1;
  });
  const [ttsVoices, setTtsVoices] = useState([]);
  const ttsVoicesForDisplay = useMemo(() => {
    const voices = Array.isArray(ttsVoices) ? [...ttsVoices] : [];

    const scoreVoice = (voice) => {
      const name = String(voice?.name || "").toLowerCase();
      const lang = String(voice?.lang || "").toLowerCase();
      let score = 0;

      if (voice?.localService) score += 2;
      if (name.includes("natural") || name.includes("neural") || name.includes("online") || name.includes("premium")) {
        score += 8;
      }
      if (name.includes("microsoft")) score += 3;
      if (lang.startsWith("en")) score += 2;
      if (lang.startsWith("en-us") || lang.startsWith("en-gb")) score += 1;

      return score;
    };

    return voices.sort((left, right) => {
      const scoreDiff = scoreVoice(right) - scoreVoice(left);
      if (scoreDiff !== 0) return scoreDiff;
      return String(left?.name || "").localeCompare(String(right?.name || ""));
    });
  }, [ttsVoices]);
  const [darkMode, setDarkMode] = useState(true);
  const [apiKeys, setApiKeys] = useState([]);
  const [keysLoading, setKeysLoading] = useState(false);
  const [keysSaving, setKeysSaving] = useState(false);
  const [keyDrafts, setKeyDrafts] = useState({});
  const [newKeyName, setNewKeyName] = useState("");
  const [newKeyValue, setNewKeyValue] = useState("");
  const [keyFeedback, setKeyFeedback] = useState("");
  const [integrations, setIntegrations] = useState([]);
  const [integrationsLoading, setIntegrationsLoading] = useState(false);
  const [integrationsSaving, setIntegrationsSaving] = useState(false);
  const [integrationFeedback, setIntegrationFeedback] = useState("");
  const [cronJobs, setCronJobs] = useState([]);
  const [cronLoading, setCronLoading] = useState(false);
  const [cronSaving, setCronSaving] = useState(false);
  const [cronFeedback, setCronFeedback] = useState("");
  const [cronSupportsSixField, setCronSupportsSixField] = useState(false);
  const [availableAgents, setAvailableAgents] = useState([]);
    const [webhooks, setWebhooks] = useState([]);
    const [webhookLoading, setWebhookLoading] = useState(false);
    const [webhookSaving, setWebhookSaving] = useState(false);
    const [webhookFeedback, setWebhookFeedback] = useState("");
    const [webhookDraft, setWebhookDraft] = useState({
      sourceId: "",
      promptTemplate: "",
      targetAgent: "",
      targetSession: "",
      priority: "0",
      paused: false,
      secretEnv: "",
    });
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [agentFeedback, setAgentFeedback] = useState("");
  const [llmProvider, setLlmProvider] = useState("openai");
  const [llmModel, setLlmModel] = useState("");
  const [llmProviders, setLlmProviders] = useState([]);
  const [llmModelsByProvider, setLlmModelsByProvider] = useState({});
  const [llmDefaults, setLlmDefaults] = useState({});
  const [llmLoading, setLlmLoading] = useState(false);
  const [llmSaving, setLlmSaving] = useState(false);
  const [llmFeedback, setLlmFeedback] = useState("");
  const [generaFeedback, setGeneraFeedback] = useState("");
  const [generaBusy, setGeneraBusy] = useState(false);
  const [generaReasoningEffort, setGeneraReasoningEffort] = useState("minimal");
  const [cronDraft, setCronDraft] = useState({
    sourceId: "",
    schedule: "",
    prompt: "",
    targetAgent: "",
    targetSession: "",
    priority: "0",
    paused: false,
  });
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
  const wakeRecognizerRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const mediaStreamRef = useRef(null);
  const audioChunksRef = useRef([]);
  const openAiTranscribeRef = useRef(false);
  const voiceModeRef = useRef("browser");
  const voiceBaseInputRef = useRef("");
  const voiceSessionActiveRef = useRef(false);
  const voiceDiscardActiveRef = useRef(false);
  const wakeListenerRunningRef = useRef(false);
  const wakePermissionCheckedRef = useRef(false);
  const wakeRestartTimerRef = useRef(null);
  const voiceSilenceTimerRef = useRef(null);
  const voiceHeardSpeechRef = useRef(false);
  const pendingAutoSendRef = useRef(false);
  const inputValueRef = useRef("");
  const voiceAudioContextRef = useRef(null);
  const voiceEnabledRef = useRef(voiceEnabled);
  const canInteractRef = useRef(canInteract);
  const isPromptActiveRef = useRef(isPromptActive);
  const hasSelectedAgentRef = useRef(hasSelectedAgent);
  const llmProviderRef = useRef(llmProvider);
  const voiceAutoSendAfterSilenceRef = useRef(voiceAutoSendAfterSilence);
  const voiceBeepEnabledRef = useRef(voiceBeepEnabled);
  const ttsEnabledRef = useRef(ttsEnabled);
  const ttsVoiceNameRef = useRef(ttsVoiceName);
  const ttsVoiceUriRef = useRef(ttsVoiceUri);
  const ttsRateRef = useRef(ttsRate);
  const pendingMcpActivityRef = useRef({});
  const activeToolRef = useRef(null);

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
      addSystem("Connected to gateway relay.");
    };

    ws.onclose = () => {
      setSocketState("closed");
      commitStream();
      addSystem("Gateway connection closed.");
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
    loadAgents();
    loadApiKeys();
    loadIntegrations();
    loadCronCapabilities();
    loadCronJobs();
    loadUserProfile();
    loadWebhooks();
    loadLlmConfig();
  }, [settingsOpen]);

  useEffect(() => {
    loadLlmConfig();
  }, []);

  useEffect(() => {
    try {
      window.localStorage.setItem("proxi.voiceEnabled", voiceEnabled ? "true" : "false");
    } catch {
      // ignore storage errors
    }
  }, [voiceEnabled]);

  useEffect(() => {
    try {
      window.localStorage.setItem("proxi.voiceSilenceSeconds", String(voiceSilenceSeconds));
    } catch {
      // ignore storage errors
    }
  }, [voiceSilenceSeconds]);

  useEffect(() => {
    try {
      window.localStorage.setItem("proxi.voiceAutoSendAfterSilence", voiceAutoSendAfterSilence ? "true" : "false");
    } catch {
      // ignore storage errors
    }
  }, [voiceAutoSendAfterSilence]);

  useEffect(() => {
    try {
      window.localStorage.setItem("proxi.voiceBeepEnabled", voiceBeepEnabled ? "true" : "false");
    } catch {
      // ignore storage errors
    }
  }, [voiceBeepEnabled]);

  useEffect(() => {
    try {
      window.localStorage.setItem("proxi.ttsEnabled", ttsEnabled ? "true" : "false");
    } catch {
      // ignore storage errors
    }

    if (!ttsEnabled && window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
  }, [ttsEnabled]);

  useEffect(() => {
    try {
      window.localStorage.setItem("proxi.ttsVoiceName", ttsVoiceName);
    } catch {
      // ignore storage errors
    }
  }, [ttsVoiceName]);

  useEffect(() => {
    try {
      window.localStorage.setItem("proxi.ttsVoiceUri", ttsVoiceUri);
    } catch {
      // ignore storage errors
    }
  }, [ttsVoiceUri]);

  useEffect(() => {
    try {
      window.localStorage.setItem("proxi.ttsRate", String(ttsRate));
    } catch {
      // ignore storage errors
    }
  }, [ttsRate]);

  useEffect(() => {
    inputValueRef.current = input;
  }, [input]);

  useEffect(() => {
    voiceEnabledRef.current = voiceEnabled;
    canInteractRef.current = canInteract;
    isPromptActiveRef.current = isPromptActive;
    hasSelectedAgentRef.current = hasSelectedAgent;
    llmProviderRef.current = llmProvider;
    voiceAutoSendAfterSilenceRef.current = voiceAutoSendAfterSilence;
    voiceBeepEnabledRef.current = voiceBeepEnabled;
    ttsEnabledRef.current = ttsEnabled;
    ttsVoiceNameRef.current = ttsVoiceName;
    ttsVoiceUriRef.current = ttsVoiceUri;
    ttsRateRef.current = ttsRate;
  }, [voiceEnabled, canInteract, isPromptActive, hasSelectedAgent, llmProvider, voiceAutoSendAfterSilence, voiceBeepEnabled, ttsEnabled, ttsVoiceName, ttsVoiceUri, ttsRate]);

  useEffect(() => {
    if (!window.speechSynthesis || !window.SpeechSynthesisUtterance) return;

    const loadVoices = () => {
      const voices = window.speechSynthesis.getVoices() || [];
      setTtsVoices(voices);
    };

    loadVoices();
    window.speechSynthesis.onvoiceschanged = loadVoices;

    return () => {
      if (window.speechSynthesis && window.speechSynthesis.onvoiceschanged === loadVoices) {
        window.speechSynthesis.onvoiceschanged = null;
      }
    };
  }, []);

  useEffect(() => {
    if (ttsVoiceName) return;
    const firstVoice = Array.isArray(ttsVoices) && ttsVoices.length > 0 ? ttsVoices[0] : null;
    if (firstVoice?.name) {
      setTtsVoiceName(firstVoice.name);
    }
  }, [ttsVoiceName, ttsVoices]);

  useEffect(() => {
    if (ttsVoiceUri || !Array.isArray(ttsVoices) || ttsVoices.length === 0) return;

    const voiceFromName = String(ttsVoiceName || "").trim()
      ? ttsVoices.find((voice) => voice.name === String(ttsVoiceName || "").trim())
      : null;

    const fallbackVoice = voiceFromName || ttsVoices[0] || null;
    if (fallbackVoice?.voiceURI) {
      setTtsVoiceUri(fallbackVoice.voiceURI);
      if (!ttsVoiceName && fallbackVoice.name) {
        setTtsVoiceName(fallbackVoice.name);
      }
    }
  }, [ttsVoiceUri, ttsVoiceName, ttsVoices]);

  useEffect(() => {
    if (!voiceEnabled || !canInteract || isPromptActive) {
      stopWakeWordListener();
      if (!voiceEnabled && (voiceSessionActiveRef.current || isListening)) {
        voiceDiscardActiveRef.current = true;
        stopActiveVoiceInput();
      }
      return;
    }

    startWakeWordListener();

    return () => {
      stopWakeWordListener();
    };
  }, [voiceEnabled, canInteract, isPromptActive, llmProvider]);

  useEffect(() => {
    if (!voiceEnabled) {
      wakePermissionCheckedRef.current = false;
      return;
    }

    if (wakePermissionCheckedRef.current) return;
    wakePermissionCheckedRef.current = true;

    (async () => {
      try {
        if (!navigator.mediaDevices?.getUserMedia) return;
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        stream.getTracks().forEach((track) => track.stop());
      } catch (error) {
        setVoiceEnabled(false);
        addSystem(`Voice wake-word disabled: ${String(error)}`);
      }
    })();
  }, [voiceEnabled]);

  useEffect(() => {
    const activeAgentId = String(bootInfo?.agentId || "").trim();
    if (!activeAgentId) return;
    setSelectedAgentId(activeAgentId);
    setAgentFeedback("");
  }, [bootInfo?.agentId]);

  async function loadAgents() {
    try {
      const response = await fetch("/api/agents");
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Failed to load agents");
      const agents = Array.isArray(payload.agents) ? payload.agents.map((a) => String(a || "")).filter(Boolean) : [];
      setAvailableAgents(agents);
      setSelectedAgentId((prev) => {
        if (prev && agents.includes(prev)) return prev;
        const activeAgentId = String(bootInfo?.agentId || "").trim();
        if (activeAgentId && agents.includes(activeAgentId)) return activeAgentId;
        return agents[0] || "";
      });

      if (agents.length > 0) {
        setCronDraft((prev) => {
          if (prev.targetAgent) return prev;
          return { ...prev, targetAgent: agents[0] };
        });
      }
    } catch {
      setAvailableAgents([]);
    }
  }

  async function loadLlmConfig() {
    setLlmLoading(true);
    setLlmFeedback("");
    try {
      const response = await fetch("/api/llm-config");
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Failed to load LLM configuration");

      const provider = String(payload?.provider || "openai").trim().toLowerCase();
      const providers = Array.isArray(payload?.providers)
        ? payload.providers.map((entry) => String(entry || "").trim().toLowerCase()).filter(Boolean)
        : [];
      const modelsByProvider = payload?.models && typeof payload.models === "object" ? payload.models : {};
      const defaults = payload?.defaults && typeof payload.defaults === "object" ? payload.defaults : {};
      const providerModels = Array.isArray(modelsByProvider?.[provider]) ? modelsByProvider[provider] : [];
      const normalizedModel = String(payload?.model || "").trim() || String(defaults?.[provider] || "").trim() || String(providerModels[0] || "").trim();

      setLlmProvider(provider);
      setLlmProviders(providers);
      setLlmModelsByProvider(modelsByProvider);
      setLlmDefaults(defaults);
      setLlmModel(normalizedModel);
    } catch (error) {
      setLlmFeedback(`Error: ${String(error)}`);
    } finally {
      setLlmLoading(false);
    }
  }

  function changeLlmProvider(provider) {
    const normalized = String(provider || "").trim().toLowerCase();
    const providerModels = Array.isArray(llmModelsByProvider?.[normalized]) ? llmModelsByProvider[normalized] : [];
    const fallbackModel =
      String(llmDefaults?.[normalized] || "").trim() ||
      String(providerModels[0] || "").trim() ||
      "";

    setLlmProvider(normalized);
    setLlmModel(fallbackModel);
    setLlmFeedback("");
  }

  async function saveLlmConfig() {
    const provider = String(llmProvider || "").trim().toLowerCase();
    const model = String(llmModel || "").trim();
    if (!provider || !model) {
      setLlmFeedback("Error: provider and model are required.");
      return;
    }

    setLlmSaving(true);
    setLlmFeedback("");
    try {
      const response = await fetch("/api/llm-config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, model }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Failed to update LLM configuration");

      setLlmProvider(String(payload?.provider || provider).trim().toLowerCase());
      setLlmModel(String(payload?.model || model).trim());
      setLlmProviders(Array.isArray(payload?.providers) ? payload.providers : llmProviders);
      setLlmModelsByProvider(payload?.models && typeof payload.models === "object" ? payload.models : llmModelsByProvider);
      setLlmDefaults(payload?.defaults && typeof payload.defaults === "object" ? payload.defaults : llmDefaults);
      setLlmFeedback("LLM updated. Existing sessions were refreshed to use this configuration.");
    } catch (error) {
      setLlmFeedback(`Error: ${String(error)}`);
    } finally {
      setLlmSaving(false);
    }
  }

  async function loadCronCapabilities() {
    try {
      const response = await fetch("/api/cron-capabilities");
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Failed to read cron capabilities");
      setCronSupportsSixField(Boolean(payload?.supportsSixField));
    } catch {
      setCronSupportsSixField(false);
    }
  }

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

  async function loadIntegrations() {
    setIntegrationsLoading(true);
    setIntegrationFeedback("");
    try {
      const response = await fetch("/api/integrations");
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Failed to load integrations");
      setIntegrations(Array.isArray(payload.integrations) ? payload.integrations : []);
    } catch (error) {
      setIntegrationFeedback(`Error: ${String(error)}`);
    } finally {
      setIntegrationsLoading(false);
    }
  }

  async function toggleIntegration(integrationName, enabled) {
    setIntegrationsSaving(true);
    setIntegrationFeedback("");
    try {
      const response = await fetch(`/api/integrations/${encodeURIComponent(integrationName)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !enabled }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Failed to update integration");

      const action = !enabled ? "enabled" : "disabled";
      setIntegrationFeedback(`${integrationName} has been ${action}. Restart the agent for changes to take effect.`);
      await loadIntegrations();
    } catch (error) {
      setIntegrationFeedback(`Error: ${String(error)}`);
    } finally {
      setIntegrationsSaving(false);
    }
  }

  async function loadCronJobs() {
    setCronLoading(true);
    setCronFeedback("");
    try {
      const response = await fetch("/api/cron-jobs");
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Failed to load cron jobs");

      const items = Array.isArray(payload.cronJobs) ? payload.cronJobs : [];
      setCronJobs(items);

      if (!cronDraft.targetAgent && items.length > 0) {
        setCronDraft((prev) => ({ ...prev, targetAgent: String(items[0].target_agent || "") }));
      }
    } catch (error) {
      setCronFeedback(`Error: ${String(error)}`);
    } finally {
      setCronLoading(false);
    }
  }

  function editCronJob(item) {
    setCronDraft({
      sourceId: String(item?.source_id || ""),
      schedule: String(item?.schedule || ""),
      prompt: String(item?.prompt || ""),
      targetAgent: String(item?.target_agent || ""),
      targetSession: String(item?.target_session || ""),
      priority: String(item?.priority ?? 0),
      paused: Boolean(item?.paused),
    });
    setCronFeedback("Editing cron job. Update fields and click Save Cron Job.");
  }

  function clearCronDraft() {
    setCronDraft({
      sourceId: "",
      schedule: "",
      prompt: "",
      targetAgent: availableAgents[0] ? String(availableAgents[0]) : "",
      targetSession: "",
      priority: "0",
      paused: false,
    });
  }

  async function saveCronJob() {
    const sourceId = cronDraft.sourceId.trim();
    const schedule = cronDraft.schedule.trim();
    const prompt = cronDraft.prompt.trim();
    const targetAgent = cronDraft.targetAgent.trim();
    const targetSession = cronDraft.targetSession.trim();
    const priority = Number.parseInt(cronDraft.priority, 10);
    const paused = Boolean(cronDraft.paused);
    const scheduleFieldCount = schedule.split(/\s+/).filter(Boolean).length;

    if (!sourceId || !schedule || !prompt || !targetAgent) {
      setCronFeedback("Error: source id, schedule, prompt, and target agent are required.");
      return;
    }

    if (!Number.isFinite(priority)) {
      setCronFeedback("Error: priority must be an integer.");
      return;
    }
    if (priority < 0 || priority > 5) {
      setCronFeedback("Error: priority must be between 0 and 5.");
      return;
    }

    if (scheduleFieldCount === 6 && !cronSupportsSixField) {
      setCronFeedback(
        "Error: this running gateway only supports 5-field cron right now. Restart gateway to enable Seconds schedules, or use Minute/Day/Week/Monthly."
      );
      return;
    }

    setCronSaving(true);
    setCronFeedback("");
    try {
      const response = await fetch(`/api/cron-jobs/${encodeURIComponent(sourceId)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          schedule,
          prompt,
          targetAgent,
          targetSession,
          priority,
          paused,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Failed to save cron job");

      setCronFeedback(`Saved cron job ${sourceId}.`);
      await loadCronJobs();
      clearCronDraft();
    } catch (error) {
      const errorText = String(error || "");
      const fieldCount = schedule.split(/\s+/).filter(Boolean).length;
      const looksLikeOldCronParser = /Expected 5-field cron expression/i.test(errorText);
      if (looksLikeOldCronParser && fieldCount === 6) {
        setCronFeedback(
          "Error: this gateway process only supports 5-field cron in its current runtime. Restart gateway, then retry the Seconds option."
        );
      } else {
        setCronFeedback(`Error: ${errorText}`);
      }
    } finally {
      setCronSaving(false);
    }
  }

  async function removeCronJob(sourceId) {
    const confirmed = window.confirm(`Delete cron job ${sourceId}?`);
    if (!confirmed) return;

    setCronSaving(true);
    setCronFeedback("");
    try {
      const response = await fetch(`/api/cron-jobs/${encodeURIComponent(sourceId)}`, {
        method: "DELETE",
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Failed to delete cron job");

      setCronFeedback(`Deleted cron job ${sourceId}.`);
      await loadCronJobs();
    } catch (error) {
      setCronFeedback(`Error: ${String(error)}`);
    } finally {
      setCronSaving(false);
    }
  }

  async function setCronJobPaused(sourceId, paused) {
    setCronSaving(true);
    setCronFeedback("");
    try {
      const response = await fetch(`/api/cron-jobs/${encodeURIComponent(sourceId)}/pause`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paused: Boolean(paused) }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Failed to update cron state");

      setCronFeedback(`${paused ? "Paused" : "Resumed"} cron job ${sourceId}.`);
      await loadCronJobs();
    } catch (error) {
      setCronFeedback(`Error: ${String(error)}`);
    } finally {
      setCronSaving(false);
    }
  }

  async function loadWebhooks() {
    setWebhookLoading(true);
    setWebhookFeedback("");
    try {
      const response = await fetch("/api/webhooks");
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Failed to load webhooks");

      const items = Array.isArray(payload.webhooks) ? payload.webhooks : [];
      setWebhooks(items);

      if (!webhookDraft.targetAgent && availableAgents.length > 0) {
        setWebhookDraft((prev) => ({ ...prev, targetAgent: String(availableAgents[0] || "") }));
      }
    } catch (error) {
      setWebhookFeedback(`Error: ${String(error)}`);
    } finally {
      setWebhookLoading(false);
    }
  }

  function editWebhook(item) {
    setWebhookDraft({
      sourceId: String(item?.source_id || ""),
      promptTemplate: String(item?.prompt_template || ""),
      targetAgent: String(item?.target_agent || ""),
      targetSession: String(item?.target_session || ""),
      priority: String(item?.priority ?? 0),
      paused: Boolean(item?.paused),
      secretEnv: String(item?.secret_env || ""),
    });
    setWebhookFeedback("Editing webhook. Update fields and click Save Webhook.");
  }

  function clearWebhookDraft() {
    setWebhookDraft({
      sourceId: "",
      promptTemplate: "",
      targetAgent: availableAgents[0] ? String(availableAgents[0]) : "",
      targetSession: "",
      priority: "0",
      paused: false,
      secretEnv: "",
    });
  }

  async function saveWebhook() {
    const sourceId = webhookDraft.sourceId.trim();
    const promptTemplate = webhookDraft.promptTemplate.trim();
    const targetAgent = webhookDraft.targetAgent.trim();
    const targetSession = webhookDraft.targetSession.trim();
    const priority = Number.parseInt(webhookDraft.priority, 10);
    const paused = Boolean(webhookDraft.paused);
    const secretEnv = webhookDraft.secretEnv.trim();

    if (!sourceId || !targetAgent) {
      setWebhookFeedback("Error: source id and target agent are required.");
      return;
    }
    if (!secretEnv) {
      setWebhookFeedback("Error: HMAC Secret Env is required for webhook security.");
      return;
    }

    if (!Number.isFinite(priority)) {
      setWebhookFeedback("Error: priority must be an integer.");
      return;
    }
    if (priority < 0 || priority > 5) {
      setWebhookFeedback("Error: priority must be between 0 and 5.");
      return;
    }

    setWebhookSaving(true);
    setWebhookFeedback("");
    try {
      const response = await fetch(`/api/webhooks/${encodeURIComponent(sourceId)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          promptTemplate,
          targetAgent,
          targetSession,
          priority,
          paused,
          secretEnv,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Failed to save webhook");

      setWebhookFeedback(`Saved webhook ${sourceId}.`);
      await loadWebhooks();
      clearWebhookDraft();
    } catch (error) {
      setWebhookFeedback(`Error: ${String(error)}`);
    } finally {
      setWebhookSaving(false);
    }
  }

  async function removeWebhook(sourceId) {
    const confirmed = window.confirm(`Delete webhook ${sourceId}?`);
    if (!confirmed) return;

    setWebhookSaving(true);
    setWebhookFeedback("");
    try {
      const response = await fetch(`/api/webhooks/${encodeURIComponent(sourceId)}`, {
        method: "DELETE",
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Failed to delete webhook");

      setWebhookFeedback(`Deleted webhook ${sourceId}.`);
      await loadWebhooks();
    } catch (error) {
      setWebhookFeedback(`Error: ${String(error)}`);
    } finally {
      setWebhookSaving(false);
    }
  }

  async function setWebhookPaused(sourceId, paused) {
    setWebhookSaving(true);
    setWebhookFeedback("");
    try {
      const response = await fetch(`/api/webhooks/${encodeURIComponent(sourceId)}/pause`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paused: Boolean(paused) }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Failed to update webhook state");

      setWebhookFeedback(`${paused ? "Paused" : "Resumed"} webhook ${sourceId}.`);
      await loadWebhooks();
    } catch (error) {
      setWebhookFeedback(`Error: ${String(error)}`);
    } finally {
      setWebhookSaving(false);
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

  function recordThinking() {
    return;
  }

  function commitStream() {
    setStreaming((prev) => {
      if (prev) {
        addAssistant(prev);
        speakAssistantResponse(prev);
      }
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

  function runSlashCommand(rawCommand, options = {}) {
    const { echo = false, successMessage = "" } = options;
    const command = String(rawCommand || "").trim();
    if (!command) return false;
    if (isPromptActive) {
      setGeneraFeedback("Complete the current prompt first.");
      addSystem("Complete the current prompt first.");
      return false;
    }
    if (!hasSelectedAgent) {
      setGeneraFeedback("Select an agent first.");
      addSystem("Select an agent first.");
      return false;
    }

    if (echo) addUser(command);
    setInput("");
    setStatusLabel("Running...");
    setStreaming("");
    send({ type: "start", task: command });
    if (successMessage) setGeneraFeedback(successMessage);
    return true;
  }

  async function clearSessionHistory() {
    if (isPromptActive) {
      setGeneraFeedback("Complete the current prompt first.");
      addSystem("Complete the current prompt first.");
      return;
    }
    if (!hasSelectedAgent) {
      setGeneraFeedback("Select an agent first.");
      addSystem("Select an agent first.");
      return;
    }

    const sessionId = String(bootInfo?.sessionId || "").trim();
    if (!sessionId) {
      setGeneraFeedback("Error: active session id is unavailable.");
      return;
    }

    setGeneraBusy(true);
    setGeneraFeedback("");
    try {
      // Match TUI behavior: clear UI immediately, then clear persisted session history.
      setMessages([]);
      setActivityItems([]);
      setStreaming("");
      setInput("");
      setBootstrapInput(null);
      setFormUi(null);
      setStatusLabel("Idle");

      const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/clear-history`, {
        method: "POST",
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || "Failed to clear session history");

      setGeneraFeedback("Session cleared (UI and persisted history).");
      addSystem("Session cleared.");
    } catch (error) {
      setGeneraFeedback(`Error: ${String(error)}`);
    } finally {
      setGeneraBusy(false);
    }
  }

  function runCompactCommand(focusHint) {
    const hint = String(focusHint || "").trim();
    const command = hint ? `/compact ${hint}` : "/compact";
    const ok = runSlashCommand(command, {
      echo: true,
      successMessage: hint
        ? `Running /compact with focus hint: ${hint}`
        : "Running /compact.",
    });
    if (ok) setGeneraFeedback((prev) => prev || "Compaction requested.");
  }

  function runReasoningEffortCommand(level) {
    const normalized = String(level || "").trim().toLowerCase();
    const valid = ["minimal", "low", "medium", "high"];
    const resolved = valid.includes(normalized) ? normalized : "minimal";
    const ok = runSlashCommand(`/reasoning-effort ${resolved}`, {
      echo: true,
      successMessage: `Reasoning effort set to ${resolved}.`,
    });
    if (ok) setGeneraReasoningEffort(resolved);
  }

  function onSwitchAgent() {
    switchAgentToSelected();
  }

  function switchAgentToSelected() {
    if (isPromptActive) {
      addSystem("Complete the current prompt first.");
      return;
    }
    if (socketState !== "connected") {
      addError("Bridge is not connected.");
      return;
    }
    const targetAgentId = String(selectedAgentId || "").trim();
    if (!targetAgentId) {
      setAgentFeedback("Select an agent before switching.");
      return;
    }
    if (targetAgentId === String(bootInfo?.agentId || "").trim()) {
      setAgentFeedback("Already using this agent.");
      return;
    }

    send({ type: "switch_agent_to", agentId: targetAgentId });
    commitStream();
    addSystem(`Switching to ${targetAgentId}...`);
    setStatusLabel("Switching...");
    setAgentFeedback(`Switching to ${targetAgentId}...`);
    setBootInfo(null);
    setBootstrapInput(null);
    setFormUi(null);
  }

  function handleMessage(msg) {
    switch (msg.type) {
      case "ready":
        setStatusLabel("Gateway ready");
        addSystem("Gateway ready.");
        break;
      case "boot_complete":
        setBootInfo({
          agentId: msg.agentId,
          sessionId: String(msg.fullSessionId || msg.sessionId || ""),
        });
        setSelectedAgentId(String(msg.agentId || ""));
        setAgentFeedback("");
        setBootstrapInput(null);
        break;
      case "text_stream":
        setStreaming((prev) => prev + (msg.content || ""));
        break;
      case "status_update":
        if (msg.status === "running") {
          if (msg.label && /thinking|reasoning/i.test(msg.label)) {
            setStatusLabel("Thinking...");
          } else {
            setStatusLabel(msg.label ? `Running: ${msg.label}` : "Running...");
          }
        } else if (msg.status === "done") {
          activeToolRef.current = null;
          setStatusLabel("Done");
          commitStream();
        }
        break;
      case "tool_start": {
        const toolName = msg.tool || "Unknown tool";
        const argsText = msg.arguments ? JSON.stringify(msg.arguments) : "";
        activeToolRef.current = {
          name: toolName,
          isMcp: isMcpToolName(toolName),
          startedAt: Date.now(),
        };
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
        if (activeToolRef.current?.name === toolName) {
          activeToolRef.current = null;
        }
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
        setStatusLabel("Thinking...");
        break;
      case "inbound_turn": {
        const sourceType = String(msg.source_type || "").toLowerCase();
        if (sourceType === "cron") {
          const sourceId = msg.source_id || "cron";
          const prompt = msg.prompt || "Scheduled job triggered.";
          addActivity("cron", `Cron triggered: ${sourceId}`, prompt);
        } else if (sourceType === "webhook") {
          const sourceId = msg.source_id || "webhook";
          const prompt = msg.prompt || "Webhook received.";
          addActivity("webhook", `Webhook arrived: ${sourceId}`, prompt);
        }
        break;
      }
      case "user_input_required":
        commitStream();
        handleUserInputRequired(msg);
        break;
      case "bridge_stderr":
        addError(`Gateway error: ${msg.content}`);
        break;
      case "bridge_exit":
        addError(`Gateway stream stopped (code=${msg.code ?? "null"}).`);
        setStatusLabel("Gateway stopped");
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

    if (window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }

    pendingAutoSendRef.current = false;
    voiceDiscardActiveRef.current = true;
    voiceBaseInputRef.current = "";
    if (voiceSessionActiveRef.current || isListening) {
      stopActiveVoiceInput();
    }

    runSlashCommand(task, { echo: true });
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

    if (window.speechSynthesis) {
      window.speechSynthesis.cancel();
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

  function normalizeTranscript(text) {
    return String(text || "").replace(/\s+/g, " ").trim();
  }

  function stripWakeWord(text) {
    const normalized = normalizeTranscript(text);
    const match = normalized.match(/(?:^|\s)hey\s+(?:proxi|proix|proxy|procksie)\b\s*(.*)$/i);
    if (!match) return "";
    return normalizeTranscript(match[1] || "");
  }

  function scheduleWakeListenerRestart() {
    if (!voiceEnabledRef.current || !canInteractRef.current || isPromptActiveRef.current || voiceSessionActiveRef.current) {
      return;
    }

    if (wakeRestartTimerRef.current) {
      clearTimeout(wakeRestartTimerRef.current);
    }

    wakeRestartTimerRef.current = setTimeout(() => {
      wakeRestartTimerRef.current = null;
      startWakeWordListener();
    }, 250);
  }

  function stopWakeWordListener() {
    if (wakeRestartTimerRef.current) {
      clearTimeout(wakeRestartTimerRef.current);
      wakeRestartTimerRef.current = null;
    }

    wakeListenerRunningRef.current = false;
    setWakeListening(false);

    const wakeRecognizer = wakeRecognizerRef.current;
    if (wakeRecognizer) {
      try {
        wakeRecognizer.abort?.();
        wakeRecognizer.stop();
      } catch {
        // ignore stop errors
      }
    }
  }

  function clearVoiceSilenceTimer() {
    if (voiceSilenceTimerRef.current) {
      clearTimeout(voiceSilenceTimerRef.current);
      voiceSilenceTimerRef.current = null;
    }
  }

  function playVoiceBeep() {
    if (!voiceBeepEnabledRef.current) return;
    if (!window.AudioContext && !window.webkitAudioContext) return;

    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!voiceAudioContextRef.current) {
        voiceAudioContextRef.current = new AudioCtx();
      }

      const context = voiceAudioContextRef.current;
      if (context.state === "suspended") {
        context.resume().catch(() => {});
      }

      const oscillator = context.createOscillator();
      const gain = context.createGain();

      oscillator.type = "sine";
      oscillator.frequency.setValueAtTime(880, context.currentTime);
      gain.gain.setValueAtTime(0.0001, context.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.06, context.currentTime + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 0.16);

      oscillator.connect(gain);
      gain.connect(context.destination);
      oscillator.start();
      oscillator.stop(context.currentTime + 0.18);

      oscillator.onended = () => {
        if (context.state === "closed") {
          voiceAudioContextRef.current = null;
        }
      };
    } catch {
      // ignore beep failures
    }
  }

  function playVoiceDoneBeep() {
    if (!voiceBeepEnabledRef.current) return;
    if (!window.AudioContext && !window.webkitAudioContext) return;

    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!voiceAudioContextRef.current) {
        voiceAudioContextRef.current = new AudioCtx();
      }

      const context = voiceAudioContextRef.current;
      if (context.state === "suspended") {
        context.resume().catch(() => {});
      }

      const firstOsc = context.createOscillator();
      const secondOsc = context.createOscillator();
      const gain = context.createGain();

      firstOsc.type = "triangle";
      secondOsc.type = "triangle";
      firstOsc.frequency.setValueAtTime(660, context.currentTime);
      secondOsc.frequency.setValueAtTime(880, context.currentTime + 0.12);

      gain.gain.setValueAtTime(0.0001, context.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.04, context.currentTime + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 0.1);
      gain.gain.exponentialRampToValueAtTime(0.04, context.currentTime + 0.14);
      gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 0.24);

      firstOsc.connect(gain);
      secondOsc.connect(gain);
      gain.connect(context.destination);
      firstOsc.start();
      firstOsc.stop(context.currentTime + 0.11);
      secondOsc.start(context.currentTime + 0.12);
      secondOsc.stop(context.currentTime + 0.25);

      secondOsc.onended = () => {
        if (context.state === "closed") {
          voiceAudioContextRef.current = null;
        }
      };
    } catch {
      // ignore beep failures
    }
  }

  function getLiveTtsVoices() {
    if (!window.speechSynthesis || !window.SpeechSynthesisUtterance) return [];
    const voices = window.speechSynthesis.getVoices?.();
    return Array.isArray(voices) ? voices : [];
  }

  function pickTtsVoice(voices) {
    const selectedVoiceUri = String(ttsVoiceUriRef.current || "").trim();
    const selectedVoiceName = String(ttsVoiceNameRef.current || "").trim();

    const scoreVoice = (voice) => {
      const name = String(voice?.name || "").toLowerCase();
      const lang = String(voice?.lang || "").toLowerCase();
      let score = 0;

      if (voice?.localService) score += 2;
      if (name.includes("natural") || name.includes("neural") || name.includes("online") || name.includes("premium")) {
        score += 8;
      }
      if (name.includes("microsoft")) score += 3;
      if (lang.startsWith("en")) score += 2;
      if (lang.startsWith("en-us") || lang.startsWith("en-gb")) score += 1;

      return score;
    };

    return (
      voices.find((voice) => voice.voiceURI === selectedVoiceUri) ||
      voices.find((voice) => voice.name === selectedVoiceName) ||
      voices.reduce((bestVoice, voice) => {
        if (!bestVoice) return voice;
        return scoreVoice(voice) > scoreVoice(bestVoice) ? voice : bestVoice;
      }, null) ||
      null
    );
  }

  function sanitizeTextForTts(rawText) {
    let text = String(rawText || "");
    if (!text) return "";

    // Drop markdown code blocks/inline code and hyperlink targets.
    text = text.replace(/```[\s\S]*?```/g, " ");
    text = text.replace(/`[^`]*`/g, " ");
    text = text.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+|www\.[^)\s]+)\)/gi, "$1");

    // Drop raw links so TTS does not read noisy URLs aloud.
    text = text.replace(/<https?:\/\/[^>]+>/gi, " ");
    text = text.replace(/https?:\/\/\S+/gi, " ");
    text = text.replace(/\bwww\.\S+/gi, " ");

    // Remove common markdown artifacts that sound awkward when spoken.
    text = text.replace(/(^|\n)\s*[-*+]\s+/g, "$1");
    text = text.replace(/[~*_#|]+/g, " ");

    return text.replace(/\s+/g, " ").trim();
  }

  function speakAssistantResponse(text, options = {}) {
    if (!ttsEnabledRef.current && !options.force) return;
    if (!window.speechSynthesis || !window.SpeechSynthesisUtterance) return;

    const spokenText = sanitizeTextForTts(text);
    if (!spokenText) return;

    try {
      const voices = getLiveTtsVoices();
      if (voices.length === 0 && (options.attempts || 0) < 6) {
        window.speechSynthesis.getVoices();
        window.setTimeout(() => {
          speakAssistantResponse(text, {
            ...options,
            attempts: (options.attempts || 0) + 1,
          });
        }, 120);
        return;
      }

      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(spokenText);
      const selectedVoice = pickTtsVoice(voices);

      if (selectedVoice) {
        utterance.voice = selectedVoice;
        utterance.lang = selectedVoice.lang || "en-US";
      }

      utterance.rate = Number.isFinite(ttsRateRef.current) ? ttsRateRef.current : 1;
      utterance.pitch = 1;
      utterance.volume = 1;
      window.speechSynthesis.speak(utterance);
    } catch {
      // ignore speech synthesis failures
    }
  }

  function queueVoiceSilenceAutoStop() {
    clearVoiceSilenceTimer();
    if (!voiceSessionActiveRef.current) return;
    if (!voiceHeardSpeechRef.current) return;

    const delayMs = Math.max(1, Number(voiceSilenceSeconds || 2)) * 1000;
    voiceSilenceTimerRef.current = setTimeout(() => {
      voiceSilenceTimerRef.current = null;
      if (!voiceSessionActiveRef.current) return;
      pendingAutoSendRef.current = Boolean(voiceAutoSendAfterSilenceRef.current);
      voiceDiscardActiveRef.current = false;
      stopActiveVoiceInput();
    }, delayMs);
  }

  function testSelectedTtsVoice() {
    speakAssistantResponse("This is Proxi testing the currently selected voice.", {
      force: true,
      attempts: 0,
    });
  }

  function sendTask(task) {
    addUser(task);
    setInput("");
    inputValueRef.current = "";
    setStatusLabel("Running...");
    setStreaming("");
    send({ type: "start", task });
  }

  function flushPendingVoiceAutoSend() {
    if (!pendingAutoSendRef.current) return;
    pendingAutoSendRef.current = false;

    const task = String(inputValueRef.current || "").trim();
    if (!task) return;
    if (isPromptActiveRef.current || !hasSelectedAgentRef.current) return;
    sendTask(task);
  }

  function ensureWakeRecognizer() {
    if (!SpeechRecognition) return null;

    if (!wakeRecognizerRef.current) {
      wakeRecognizerRef.current = new SpeechRecognition();
      wakeRecognizerRef.current.continuous = false;
      wakeRecognizerRef.current.interimResults = true;
      wakeRecognizerRef.current.lang = "en-US";

      wakeRecognizerRef.current.onstart = () => {
        wakeListenerRunningRef.current = true;
        setWakeListening(true);
      };

      wakeRecognizerRef.current.onresult = (evt) => {
        if (!voiceEnabledRef.current || voiceSessionActiveRef.current) return;

        for (let i = evt.resultIndex; i < evt.results.length; i++) {
          const candidate = normalizeTranscript(evt.results[i]?.[0]?.transcript || "");
          if (!candidate || !/hey\s+(?:proxi|proix|proxy|procksie)\b/i.test(candidate)) continue;

          const command = stripWakeWord(candidate);
          voiceSessionActiveRef.current = true;
          voiceDiscardActiveRef.current = false;
          stopWakeWordListener();
          beginVoiceCapture(command);
          break;
        }
      };

      wakeRecognizerRef.current.onerror = (evt) => {
        wakeListenerRunningRef.current = false;
        setWakeListening(false);
        if (voiceEnabledRef.current && !voiceSessionActiveRef.current) {
          const err = String(evt?.error || "").toLowerCase();
          if (err !== "not-allowed" && err !== "service-not-allowed") {
            scheduleWakeListenerRestart();
          }
        }
      };

      wakeRecognizerRef.current.onend = () => {
        wakeListenerRunningRef.current = false;
        setWakeListening(false);
        if (voiceEnabledRef.current && canInteractRef.current && !isPromptActiveRef.current && !voiceSessionActiveRef.current) {
          scheduleWakeListenerRestart();
        }
      };
    }

    return wakeRecognizerRef.current;
  }

  function startWakeWordListener() {
    if (!voiceEnabledRef.current || !canInteractRef.current || isPromptActiveRef.current || voiceSessionActiveRef.current) {
      return;
    }

    const wakeRecognizer = ensureWakeRecognizer();
    if (!wakeRecognizer || wakeListenerRunningRef.current) {
      return;
    }

    try {
      wakeRecognizer.start();
      wakeListenerRunningRef.current = true;
      setWakeListening(true);
    } catch {
      wakeListenerRunningRef.current = false;
      setWakeListening(false);
      scheduleWakeListenerRestart();
    }
  }

  function finishVoiceSession() {
    const hadActiveSession = voiceSessionActiveRef.current || isListening;
    clearVoiceSilenceTimer();
    voiceHeardSpeechRef.current = false;
    voiceSessionActiveRef.current = false;
    voiceDiscardActiveRef.current = false;
    if (hadActiveSession) {
      playVoiceDoneBeep();
    }
    if (voiceEnabledRef.current && canInteractRef.current && !isPromptActiveRef.current) {
      startWakeWordListener();
    }
    setTimeout(() => {
      flushPendingVoiceAutoSend();
    }, 0);
  }

  function clearOpenAiVoiceState() {
    const stream = mediaStreamRef.current;
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
    }

    mediaRecorderRef.current = null;
    mediaStreamRef.current = null;
    audioChunksRef.current = [];
  }

  function composeVoiceInput(transcript) {
    const base = String(voiceBaseInputRef.current || "").trim();
    const spoken = String(transcript || "").trim();
    if (!base) return spoken;
    if (!spoken) return base;
    return `${base} ${spoken}`;
  }

  function applyVoiceTranscript(transcript) {
    const normalized = normalizeTranscript(transcript);
    setInput(composeVoiceInput(normalized));
    if (normalized) {
      voiceHeardSpeechRef.current = true;
      queueVoiceSilenceAutoStop();
    }
  }

  function beginVoiceCapture(initialTranscript = "") {
    const normalizedInitial = normalizeTranscript(initialTranscript);
    const provider = String(llmProviderRef.current || "").trim().toLowerCase();

    voiceHeardSpeechRef.current = false;
    voiceSessionActiveRef.current = true;
    pendingAutoSendRef.current = false;
    voiceDiscardActiveRef.current = false;
    voiceBaseInputRef.current = String(inputValueRef.current || "");

    if (normalizedInitial) {
      applyVoiceTranscript(normalizedInitial);
    }

    if (provider === "openai") {
      startOpenAiVoiceInput(normalizedInitial);
      return;
    }

    startBrowserVoiceInput(normalizedInitial);
  }

  function readSpeechRecognitionTranscript(evt) {
    const parts = [];
    for (let i = 0; i < evt.results.length; i++) {
      const result = evt.results[i];
      const transcript = String(result?.[0]?.transcript || "").trim();
      if (transcript) {
        parts.push(transcript);
      }
    }
    return parts.join(" ").replace(/\s+/g, " ").trim();
  }

  function attachSpeechRecognitionHandlers() {
    if (!SpeechRecognition || recognizerRef.current) return recognizerRef.current;

    recognizerRef.current = new SpeechRecognition();
    recognizerRef.current.continuous = false;
    recognizerRef.current.interimResults = true;
    recognizerRef.current.lang = "en-US";

    recognizerRef.current.onstart = () => {
      setIsListening(true);
      playVoiceBeep();
    };
    recognizerRef.current.onresult = (evt) => {
      const transcript = readSpeechRecognitionTranscript(evt);
      if (!voiceSessionActiveRef.current) return;
      applyVoiceTranscript(transcript);
    };
    recognizerRef.current.onerror = (evt) => {
      addError(`Speech error: ${evt.error}`);
      setIsListening(false);
      if (voiceSessionActiveRef.current) {
        voiceSessionActiveRef.current = false;
        finishVoiceSession();
      }
    };
    recognizerRef.current.onend = () => {
      if (voiceModeRef.current === "openai" && mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
        return;
      }
      setIsListening(false);
      if (voiceSessionActiveRef.current) {
        finishVoiceSession();
      }
    };

    return recognizerRef.current;
  }

  function startBrowserVoiceInput(initialTranscript = "") {
    if (!SpeechRecognition) {
      alert("Speech Recognition not supported in this browser.");
      voiceSessionActiveRef.current = false;
      finishVoiceSession();
      return;
    }

    voiceModeRef.current = "browser";
    voiceHeardSpeechRef.current = false;
    voiceSessionActiveRef.current = true;
    voiceDiscardActiveRef.current = false;
    voiceBaseInputRef.current = String(inputValueRef.current || "");

    const normalizedInitial = normalizeTranscript(initialTranscript);
    if (normalizedInitial) {
      applyVoiceTranscript(normalizedInitial);
    }

    const recognizer = attachSpeechRecognitionHandlers();
    if (!recognizer) {
      voiceSessionActiveRef.current = false;
      finishVoiceSession();
      return;
    }

    try {
      recognizer.start();
    } catch {
      voiceSessionActiveRef.current = false;
      finishVoiceSession();
    }
  }

  function stopBrowserVoiceInput() {
    clearVoiceSilenceTimer();
    recognizerRef.current?.stop();
    setIsListening(false);
  }

  function stopOpenAiVoiceInput() {
    clearVoiceSilenceTimer();
    const recorder = mediaRecorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      openAiTranscribeRef.current = !voiceDiscardActiveRef.current;
      recorder.stop();
    }

    recognizerRef.current?.stop();
  }

  function stopActiveVoiceInput() {
    if (voiceModeRef.current === "openai") {
      stopOpenAiVoiceInput();
      return;
    }

    stopBrowserVoiceInput();
  }

  async function blobToBase64(blob) {
    const buffer = await blob.arrayBuffer();
    const bytes = new Uint8Array(buffer);
    const chunkSize = 0x8000;
    let binary = "";

    for (let index = 0; index < bytes.length; index += chunkSize) {
      binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize));
    }

    return window.btoa(binary);
  }

  async function transcribeOpenAiAudio(blob, mimeType) {
    const audioBase64 = await blobToBase64(blob);
    const response = await fetch("/api/transcribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ audioBase64, mimeType }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || "Failed to transcribe voice input");
    }
    return String(payload?.text || "").trim();
  }

  async function startOpenAiVoiceInput(initialTranscript = "") {
    if (!window.MediaRecorder || !navigator.mediaDevices?.getUserMedia) {
      addError("OpenAI voice input is not supported in this browser.");
      voiceSessionActiveRef.current = false;
      finishVoiceSession();
      return;
    }

    const preferredMimeTypes = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
    const mimeType =
      preferredMimeTypes.find((candidate) => window.MediaRecorder.isTypeSupported?.(candidate)) ||
      "audio/webm";

    try {
      voiceModeRef.current = "openai";
      voiceHeardSpeechRef.current = false;
      voiceSessionActiveRef.current = true;
      voiceDiscardActiveRef.current = false;
      voiceBaseInputRef.current = String(inputValueRef.current || "");
      const normalizedInitial = normalizeTranscript(initialTranscript);
      if (normalizedInitial) {
        applyVoiceTranscript(normalizedInitial);
      }

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream, { mimeType });

      openAiTranscribeRef.current = true;
      audioChunksRef.current = [];
      mediaStreamRef.current = stream;
      mediaRecorderRef.current = recorder;

      recorder.onstart = () => {
        setIsListening(true);
        playVoiceBeep();
      };
      recorder.ondataavailable = (evt) => {
        if (evt.data && evt.data.size > 0) {
          audioChunksRef.current.push(evt.data);
        }
      };
      recorder.onerror = (evt) => {
        addError(`Voice recording error: ${evt.error?.message || evt.error || "unknown"}`);
        openAiTranscribeRef.current = false;
        clearOpenAiVoiceState();
        setIsListening(false);
        voiceSessionActiveRef.current = false;
        finishVoiceSession();
      };
      recorder.onstop = async () => {
        const shouldTranscribe = openAiTranscribeRef.current;
        openAiTranscribeRef.current = false;
        setIsListening(false);

        const chunks = audioChunksRef.current.slice();
        clearOpenAiVoiceState();

        if (!shouldTranscribe || chunks.length === 0) {
          finishVoiceSession();
          return;
        }

        try {
          const transcript = await transcribeOpenAiAudio(new Blob(chunks, { type: mimeType }), mimeType);
          if (transcript) {
            applyVoiceTranscript(transcript);
          }
        } catch (error) {
          addError(`OpenAI voice input failed: ${String(error)}`);
        }

        finishVoiceSession();
      };

      if (SpeechRecognition) {
        const recognizer = attachSpeechRecognitionHandlers();
        if (recognizer) {
          recognizer.start();
        }
      }

      recorder.start();
    } catch (error) {
      clearOpenAiVoiceState();
      setIsListening(false);
      voiceSessionActiveRef.current = false;
      finishVoiceSession();
      addError(`Unable to start OpenAI voice input: ${String(error)}`);
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

    if (isListening || voiceSessionActiveRef.current) {
      stopActiveVoiceInput();
      return;
    }

    voiceDiscardActiveRef.current = false;
    stopWakeWordListener();
    beginVoiceCapture();
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
            <span aria-hidden="true">{darkMode ? "☾" : "☀"}</span>
          </button>
          <button
            className="switchAgentBtn"
            onClick={() => setSettingsOpen(true)}
            disabled={socketState !== "connected" || isPromptActive}
            title="Open settings to switch agent"
            aria-label="Open settings to switch agent"
          >
            <i className="fa-solid fa-arrows-rotate" aria-hidden="true"></i>
          </button>
          <div className="headerStatus">
            <span className={`statusDot ${socketState}`}></span>
            {connectionText} - {statusLabel}
          </div>
          <div className={`headerStatus ${voiceEnabled ? "voiceOn" : "voiceOff"}`} title={voiceEnabled ? "Wake-word listening is enabled" : "Wake-word listening is disabled"}>
            {voiceEnabled ? (isListening ? "Voice active" : "Voice ready") : "Voice off"}
          </div>
        </div>
      </div>

      <ChatView
        chatRef={chatRef}
        messages={messages}
        activityItems={activityItems}
        activityCollapsed={activityCollapsed}
        onToggleActivity={() => setActivityCollapsed((prev) => !prev)}
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
        selectedAgentId={selectedAgentId}
        setSelectedAgentId={setSelectedAgentId}
        agentFeedback={agentFeedback}
        switchAgentToSelected={switchAgentToSelected}
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
        integrationsLoading={integrationsLoading}
        integrationsSaving={integrationsSaving}
        integrationFeedback={integrationFeedback}
        integrations={integrations}
        toggleIntegration={toggleIntegration}
        loadIntegrations={loadIntegrations}
        cronJobs={cronJobs}
        cronLoading={cronLoading}
        cronSaving={cronSaving}
        cronFeedback={cronFeedback}
        cronSupportsSixField={cronSupportsSixField}
        availableAgents={availableAgents}
        cronDraft={cronDraft}
        setCronDraft={setCronDraft}
        saveCronJob={saveCronJob}
        removeCronJob={removeCronJob}
        setCronJobPaused={setCronJobPaused}
        loadCronJobs={loadCronJobs}
        editCronJob={editCronJob}
        clearCronDraft={clearCronDraft}
        llmProvider={llmProvider}
        llmModel={llmModel}
        llmProviders={llmProviders}
        llmModelsByProvider={llmModelsByProvider}
        llmLoading={llmLoading}
        llmSaving={llmSaving}
        llmFeedback={llmFeedback}
        changeLlmProvider={changeLlmProvider}
        setLlmModel={setLlmModel}
        saveLlmConfig={saveLlmConfig}
        loadLlmConfig={loadLlmConfig}
        generaFeedback={generaFeedback}
        generaBusy={generaBusy}
        generaReasoningEffort={generaReasoningEffort}
        runCompactCommand={runCompactCommand}
        runReasoningEffortCommand={runReasoningEffortCommand}
        clearSessionHistory={clearSessionHistory}
        voiceEnabled={voiceEnabled}
        setVoiceEnabled={setVoiceEnabled}
        voiceSilenceSeconds={voiceSilenceSeconds}
        setVoiceSilenceSeconds={setVoiceSilenceSeconds}
        voiceAutoSendAfterSilence={voiceAutoSendAfterSilence}
        setVoiceAutoSendAfterSilence={setVoiceAutoSendAfterSilence}
        voiceBeepEnabled={voiceBeepEnabled}
        setVoiceBeepEnabled={setVoiceBeepEnabled}
        ttsEnabled={ttsEnabled}
        setTtsEnabled={setTtsEnabled}
        ttsVoices={ttsVoicesForDisplay}
        ttsVoiceName={ttsVoiceName}
        setTtsVoiceName={setTtsVoiceName}
        ttsVoiceUri={ttsVoiceUri}
        setTtsVoiceUri={setTtsVoiceUri}
        ttsRate={ttsRate}
        setTtsRate={setTtsRate}
        testTtsVoice={testSelectedTtsVoice}
        webhooks={webhooks}
        webhookLoading={webhookLoading}
        webhookSaving={webhookSaving}
        webhookFeedback={webhookFeedback}
        webhookDraft={webhookDraft}
        setWebhookDraft={setWebhookDraft}
        saveWebhook={saveWebhook}
        removeWebhook={removeWebhook}
        setWebhookPaused={setWebhookPaused}
        loadWebhooks={loadWebhooks}
        editWebhook={editWebhook}
        clearWebhookDraft={clearWebhookDraft}
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
