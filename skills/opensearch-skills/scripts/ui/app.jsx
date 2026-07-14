// Loaded as a classic <script type="text/babel"> in index.html; all UI
// files share one global scope (no bundler). Load order is defined there.

// ---------------------------------------------------------------------------
// Main App
// ---------------------------------------------------------------------------
function App() {
  const [indexName, setIndexName] = useState("");
  const [searchSize, setSearchSize] = useState("20");
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [stats, setStats] = useState("Ready");
  const [queryMode, setQueryMode] = useState("");
  const [capability, setCapability] = useState("");
  const [fallbackReason, setFallbackReason] = useState("");
  const [usedSemantic, setUsedSemantic] = useState(false);
  const [autocompleteField, setAutocompleteField] = useState("");
  const [autocompleteOptions, setAutocompleteOptions] = useState([]);
  const [backendType, setBackendType] = useState("");
  const [backendEndpoint, setBackendEndpoint] = useState("");
  const [backendConnected, setBackendConnected] = useState(false);

  // Comparison mode state
  const [comparisonAvailable, setComparisonAvailable] = useState(false);
  const [comparisonEnabled, setComparisonEnabled] = useState(false);
  const [compareIndex1, setCompareIndex1] = useState("");
  const [compareIndex2, setCompareIndex2] = useState("");
  const [availableIndices, setAvailableIndices] = useState([]);

  // Template & settings state
  const [schema, setSchema] = useState(null);
  const [activeTemplate, setActiveTemplate] = useState("document");
  const [showSettings, setShowSettings] = useState(false);
  const [darkMode, setDarkMode] = useState(false);

  // View toggle: "search" (default) or "ingestion"
  const [activeView, setActiveView] = useState("search");
  // Tracks whether we've already auto-switched to ingestion for the current active job.
  // Prevents the poll from yanking the user back if they manually switch to Search.
  const didAutoSwitchRef = useRef(false);
  const [uiMode, setUiMode] = useState("full");  // full | ingestion | search (from /api/config)
  const [showIngestionTab, setShowIngestionTab] = useState(false);  // server-computed: local endpoint + local chunks
  const [ingestionChunkIndex, setIngestionChunkIndex] = useState("");  // resolved chunk set for current index (same-name or provenance parent)
  const [ingestionIndex, setIngestionIndex] = useState("");  // chunk set currently shown in the ingestion view (user can browse cross-index)
  const [ingestionIndexOptions, setIngestionIndexOptions] = useState([]);  // all chunk sets under .opensearch/chunks (from /api/ingestion-indices)
  const [ingestionStatus, setIngestionStatus] = useState(null);

  // Chat / agent state
  const [chatMessages, setChatMessages] = useState([]);
  const [memoryId, setMemoryId] = useState(null);
  const [prevComparisonEnabled, setPrevComparisonEnabled] = useState(false);
  const [ragAnswer, setRagAnswer] = useState("");
  const [agentStepsSummary, setAgentStepsSummary] = useState("");
  const [dslQuery, setDslQuery] = useState("");
  // "search" = google-like (flow agent), "chat" = chatbox (conversational agent)
  const [agenticMode, setAgenticMode] = useState("search");
  const [agentPrompts, setAgentPrompts] = useState({ search: [], chat: [] });
  const [agentPromptsLoaded, setAgentPromptsLoaded] = useState(false);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", darkMode);
  }, [darkMode]);

  // Poll ingestion status + endpoint every 2s
  useEffect(() => {
    const poll = async () => {
      try {
        // Ingestion status
        const res = await fetch("/api/ingestion-status");
        if (res.ok) {
          const data = await res.json();
          setIngestionStatus(data);
          if (data.active && !didAutoSwitchRef.current && activeView === "search" && uiMode !== "search" && (showIngestionTab || uiMode === "ingestion")) {
            setActiveView("ingestion");
            didAutoSwitchRef.current = true;
          }
          // Reset the flag when ingestion finishes so next job can auto-switch again
          if (!data.active) {
            didAutoSwitchRef.current = false;
          }
        }
        // Refresh endpoint (picks up connect-ui changes)
        const idxParam = indexName.trim() ? `?index=${encodeURIComponent(indexName.trim())}` : "";
        const cfgRes = await fetch(`/api/config${idxParam}`);
        if (cfgRes.ok) {
          const cfg = await cfgRes.json();
          setBackendEndpoint(String(cfg.endpoint || "").trim());
          setBackendConnected(Boolean(cfg.connected));
          setShowIngestionTab(Boolean(cfg.show_ingestion_tab));
          // Resolved chunk set for the current index (same-name or provenance
          // parent). The ingestion view defaults here; the user may browse to
          // any other chunk set via the ingestion-view picker (ingestionIndex).
          setIngestionChunkIndex(String(cfg.ingestion_chunk_index || ""));
          const mode = String(cfg.ui_mode || "full");
          setUiMode(mode);
          // In ingestion-only mode, default to the ingestion view.
          if (mode === "ingestion") setActiveView(v => (v === "search" ? "ingestion" : v));
          if (mode === "search") setActiveView(v => (v === "ingestion" ? "search" : v));
        }
      } catch (e) { /* ignore */ }
    };
    poll();
    const interval = setInterval(poll, 2000);
    return () => clearInterval(interval);
  }, [activeView, uiMode, indexName, showIngestionTab]);

  // Field mapping overrides
  const [titleField, setTitleField] = useState("(none)");
  const [descField, setDescField] = useState("(none)");
  const [imgField, setImgField] = useState("(none)");
  const [hiddenFields, setHiddenFields] = useState(new Set());

  const fieldOverrides = {
    title: titleField !== "(none)" ? titleField : null,
    description: descField !== "(none)" ? descField : null,
    image: imgField !== "(none)" ? imgField : null,
  };

  const toggleHiddenField = (field) => {
    setHiddenFields((prev) => {
      const next = new Set(prev);
      if (next.has(field)) next.delete(field);
      else next.add(field);
      return next;
    });
  };

  const filterSource = (source) => {
    if (!source || hiddenFields.size === 0) return source;
    const out = {};
    for (const [k, v] of Object.entries(source)) {
      if (!hiddenFields.has(k)) out[k] = v;
    }
    return out;
  };

  const capabilityLabel = {
    exact: "Exact",
    semantic: "Semantic",
    structured: "Structured",
    combined: "Combined",
    autocomplete: "Autocomplete",
    fuzzy: "Fuzzy",
    manual: "Manual",
  };

  // ---- Template change with comparison mode management ----
  const handleTemplateChange = (newTemplate) => {
    if (newTemplate === "agent" && activeTemplate !== "agent") {
      setPrevComparisonEnabled(comparisonEnabled);
      setComparisonEnabled(false);
    } else if (newTemplate !== "agent" && activeTemplate === "agent") {
      setComparisonEnabled(prevComparisonEnabled);
    }
    setActiveTemplate(newTemplate);
  };

  // ---- Schema fetch ----
  const schemaLoadedRef = useRef("");  // last index the suggested template was applied for
  const fetchSchema = useCallback(async (index) => {
    if (!index) return;
    try {
      const res = await fetch(`/api/schema?index=${encodeURIComponent(index)}`);
      const data = await res.json();
      if (!data.error) {
        setSchema(data);
        // Always update agentic mode when agent type changes
        if (data.agentic_agent_type) {
          setAgenticMode(data.agentic_agent_type === "conversational" ? "chat" : "search");
        }
        // Apply the suggested template once per index. Re-applies when the
        // index changes (so switching indices picks up the new AUTO template),
        // but not on same-index refetches (so a manual template choice sticks).
        if (schemaLoadedRef.current !== index) {
          schemaLoadedRef.current = index;
          const suggested = data.suggested_template || "document";
          setActiveTemplate(suggested);
          if (suggested === "agent") {
            setComparisonEnabled(false);
          }
          if (data.agentic_agent_type) {
            loadAgentPrompts(index);
          }
        }
      }
    } catch (_) {}
  }, []);

  // ---- Agent Prompts ----
  const loadAgentPrompts = async (index) => {
    if (!index) return;
    setAgentPromptsLoaded(false);
    // Race: API response vs 5s timeout for fallback
    const fallbackTimer = setTimeout(() => {
      setAgentPromptsLoaded(true);
    }, 5000);
    try {
      const res = await fetch(`/api/agent-prompts?index=${encodeURIComponent(index)}`);
      const data = await res.json();
      clearTimeout(fallbackTimer);
      if ((data.search && data.search.length > 0) || (data.chat && data.chat.length > 0)) {
        setAgentPrompts(data);
      }
      setAgentPromptsLoaded(true);
    } catch (_) {
      clearTimeout(fallbackTimer);
      setAgentPromptsLoaded(true);
    }
  };

  // ---- Suggestions ----
  const loadSuggestions = async (index) => {
    try {
      const qs = new URLSearchParams();
      if (index) qs.set("index", index);
      const res = await fetch(`/api/suggestions?${qs.toString()}`);
      const data = await res.json();
      const raw = Array.isArray(data.suggestions) ? data.suggestions : [];
      const mapped = raw
        .map((entry) => ({
          text: String(entry.text || "").trim(),
          capability: String(entry.capability || "").trim().toLowerCase(),
          query_mode: String(entry.query_mode || "default").trim(),
          field: String(entry.field || "").trim(),
          value: String(entry.value || "").trim(),
          case_insensitive: Boolean(entry.case_insensitive),
        }))
        .filter((entry) => entry.text.length > 0 && entry.capability.length > 0);
      setSuggestions(mapped);
    } catch (_) { setSuggestions([]); }
  };

  // ---- Config ----
  const loadConfig = async () => {
    try {
      const res = await fetch("/api/config");
      const data = await res.json();
      setBackendType(String(data.backend_type || "").trim());
      setBackendEndpoint(String(data.endpoint || "").trim());
      setBackendConnected(Boolean(data.connected));
      const defaultIndex = (data.default_index || "").trim();
      if (defaultIndex) {
        setIndexName(defaultIndex);
        await loadSuggestions(defaultIndex);
        await fetchSchema(defaultIndex);
        return;
      }
      await loadSuggestions("");
    } catch (_err) {
      await loadSuggestions("");
    }
  };

  const loadComparisonConfig = async () => {
    try {
      const res = await fetch("/api/comparison-config");
      const data = await res.json();
      if (data.comparison_enabled) {
        setComparisonAvailable(true);
        setComparisonEnabled(true);
        setCompareIndex1(data.baseline_index);
        setCompareIndex2(data.improved_index);
        // Use index 2 for suggestions and schema in comparison mode
        await loadSuggestions(data.improved_index);
        await fetchSchema(data.improved_index);
      }
    } catch (err) {
      console.error("Failed to fetch comparison config:", err);
    }
  };

  const loadIndices = async () => {
    try {
      const res = await fetch("/api/indices");
      const data = await res.json();
      const list = Array.isArray(data.indices) ? data.indices : [];
      setAvailableIndices(list);
      // Comparison is a search feature — only cluster-backed indices count.
      if (list.filter((i) => i.source !== "local").length >= 2) setComparisonAvailable(true);
    } catch (_) {}
  };

  useEffect(() => { loadConfig(); loadComparisonConfig(); loadIndices(); }, []);

  // Refetch schema when index changes (debounced)
  useEffect(() => {
    const idx = indexName.trim();
    if (!idx) return;
    // Reset the ingestion-view picker so it re-defaults to the new index's
    // resolved chunk set (via ingestion_chunk_index from /api/config).
    setIngestionIndex("");
    const timer = setTimeout(() => fetchSchema(idx), 400);
    return () => clearTimeout(timer);
  }, [indexName, fetchSchema]);

  // Load all chunk sets for the ingestion-view cross-index picker.
  useEffect(() => {
    fetch("/api/ingestion-indices")
      .then(r => r.json())
      .then(d => setIngestionIndexOptions(Array.isArray(d.indices) ? d.indices : []))
      .catch(() => {});
  }, [ingestionChunkIndex]);

  // ---- Autocomplete ----
  useEffect(() => {
    const effectiveIndex = (comparisonEnabled && compareIndex2) ? compareIndex2 : indexName.trim();
    const prefix = query.trim();
    const autocompleteActive = effectiveIndex.length > 0 && prefix.length >= 2;

    if (!autocompleteActive) {
      setAutocompleteOptions([]);
      return;
    }

    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const qs = new URLSearchParams();
        qs.set("index", effectiveIndex);
        qs.set("q", prefix);
        qs.set("size", "8");
        if (autocompleteField) {
          qs.set("field", autocompleteField);
        }
        const res = await fetch(`/api/autocomplete?${qs.toString()}`);
        const data = await res.json();
        const resolvedField = String(data.field || "").trim();
        const options = Array.isArray(data.options)
          ? data.options
              .map((value) => String(value || "").trim())
              .filter((value) => value.length > 0)
          : [];
        if (!cancelled) {
          if (resolvedField) {
            setAutocompleteField((prev) => (prev === resolvedField ? prev : resolvedField));
          }
          setAutocompleteOptions(options);
        }
      } catch (_err) {
        if (!cancelled) {
          setAutocompleteOptions([]);
        }
      }
    }, 120);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [indexName, query, capability, queryMode, autocompleteField, comparisonEnabled, compareIndex2]);

  // ---- Agent Search ----
  const runAgentSearch = async (overrideQuery = null) => {
    const effectiveQuery = (overrideQuery !== null ? overrideQuery : query).trim();
    const effectiveIndex = indexName.trim();
    if (!effectiveIndex || !effectiveQuery) return;

    setChatMessages(prev => [...prev, { role: "user", text: effectiveQuery }]);
    setLoading(true);
    setError("");

    try {
      const qs = new URLSearchParams();
      qs.set("index", effectiveIndex);
      qs.set("q", effectiveQuery);
      qs.set("size", String(parseInt(searchSize, 10) || 20));
      qs.set("debug", "1");
      if (memoryId) qs.set("memory_id", memoryId);

      const res = await fetch(`/api/search?${qs.toString()}`);
      const data = await res.json();

      if (data.error) {
        const friendlyError = data.error.includes("expired") 
          ? "AI agent credentials have expired. Please refresh and try again."
          : data.error.includes("timeout") 
          ? "The AI agent took too long to respond. Please try a simpler question."
          : "I had trouble processing your question. Please try rephrasing it.";
        setChatMessages(prev => [...prev, { role: "assistant", error: friendlyError }]);
      } else {
        const hits = Array.isArray(data.hits) ? data.hits : [];
        const summary = generateChatSummary(effectiveQuery, hits, data.total ?? 0, schema);
        setChatMessages(prev => [...prev, {
          role: "assistant",
          query: effectiveQuery,
          results: hits,
          total: data.total ?? 0,
          took_ms: data.took_ms ?? 0,
          capability: data.capability || "",
          summary: data.rag_answer || summary,
          agent_steps_summary: data.agent_steps_summary || "",
          dsl_query: data.dsl_query || "",
        }]);
        if (data.memory_id) setMemoryId(data.memory_id);
      }
    } catch (err) {
      setChatMessages(prev => [...prev, { role: "assistant", error: "Something went wrong. Please try again." }]);
    } finally {
      setLoading(false);
      setQuery("");
    }
  };

  // ---- Search ----
  const runSearch = async (overrideQuery = null, options = {}) => {
    if (activeTemplate === "agent" && agenticMode === "chat") { runAgentSearch(overrideQuery); return; }
    // In comparison mode, ComparisonView handles search via its own useEffect on query
    if (comparisonEnabled) return;
    const effectiveQuery = (overrideQuery !== null ? overrideQuery : query).trim();
    const effectiveIndex = indexName.trim();
    const effectiveSize = parseInt(searchSize, 10) || 20;
    if (!effectiveIndex) { setError("Please enter an index name."); return; }

    setError("");
    setLoading(true);

    try {
      const qs = new URLSearchParams();
      qs.set("index", effectiveIndex);
      qs.set("q", effectiveQuery);
      qs.set("size", String(effectiveSize));
      qs.set("debug", "1");
      if (options.intent) qs.set("intent", options.intent);
      if (options.field) qs.set("field", options.field);
      const res = await fetch(`/api/search?${qs.toString()}`);
      const data = await res.json();

      if (data.error) {
        setError(data.error);
        setResults([]);
        setStats("Search failed");
        setQueryMode(""); setCapability(""); setFallbackReason(""); setUsedSemantic(false);
      } else {
        const hits = Array.isArray(data.hits) ? data.hits : [];
        setResults(hits);
        setStats(`Loaded ${data.total ?? 0} hit(s) in ${data.took_ms ?? 0} ms`);
        setQueryMode(String(data.query_mode || ""));
        setCapability(String(data.capability || ""));
        setFallbackReason(String(data.fallback_reason || ""));
        setUsedSemantic(Boolean(data.used_semantic));
        setRagAnswer(String(data.rag_answer || ""));
        setAgentStepsSummary(String(data.agent_steps_summary || ""));
        setDslQuery(String(data.dsl_query || ""));
        await loadSuggestions(effectiveIndex);
      }
    } catch (err) {
      setError(`Request failed: ${err.message}`);
      setResults([]);
      setStats("Search failed");
      setQueryMode(""); setCapability(""); setFallbackReason(""); setUsedSemantic(false);
    } finally {
      setLoading(false);
    }
  };

  const onSuggestionClick = (entry) => {
    const text = String(entry?.text || "").trim();
    if (!text) return;
    setAutocompleteField(String(entry?.capability || "").toLowerCase() === "autocomplete" ? String(entry?.field || "") : "");
    setAutocompleteOptions([]);
    setQuery(text);
    runSearch(text);
  };

  const onAutocompleteOptionClick = (value) => {
    const text = String(value || "").trim();
    if (!text) return;
    setAutocompleteOptions([]);
    setQuery(text);
    runSearch(text, { intent: "autocomplete_selection", field: autocompleteField });
  };

  // Derive field lists from schema for field mapping dropdowns
  const allFields = schema?.field_specs ? Object.keys(schema.field_specs).filter((f) => !f.endsWith(".keyword")) : [];
  const textFields = (schema?.field_categories?.text || []);
  // Cluster-backed indices only for the search pickers. Chunk-only entries
  // (source==="local", i.e. .opensearch/chunks/<name> with no cluster index)
  // aren't searchable — they belong to the Ingestion view's chunk-set picker.
  const searchableIndices = availableIndices.filter((i) => i.source !== "local");

  return (
    <div className={`shell template-${activeTemplate}`}>
      <header className="topbar">
        <div className="brand">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 42.6667 42.6667" fill="none" aria-label="OpenSearch" role="img">
            <path className="logo-light" fill="#075985" d="M41.1583 15.6667C40.3252 15.6667 39.6499 16.342 39.6499 17.1751C39.6499 29.5876 29.5876 39.6499 17.1751 39.6499C16.342 39.6499 15.6667 40.3252 15.6667 41.1583C15.6667 41.9913 16.342 42.6667 17.1751 42.6667C31.2537 42.6667 42.6667 31.2537 42.6667 17.1751C42.6667 16.342 41.9913 15.6667 41.1583 15.6667Z"/>
            <path className="logo-dark" fill="#082F49" d="M32.0543 25.3333C33.5048 22.967 34.9077 19.8119 34.6317 15.3947C34.06 6.24484 25.7726 -0.696419 17.9471 0.0558224C14.8835 0.350311 11.7379 2.84747 12.0173 7.32032C12.1388 9.26409 13.0902 10.4113 14.6363 11.2933C16.1079 12.1328 17.9985 12.6646 20.1418 13.2674C22.7308 13.9956 25.7339 14.8135 28.042 16.5144C30.8084 18.553 32.6994 20.9162 32.0543 25.3333Z"/>
            <path className="logo-light" fill="#075985" d="M2.6124 9.33333C1.16184 11.6997 -0.241004 14.8548 0.0349954 19.2719C0.606714 28.4218 8.89407 35.3631 16.7196 34.6108C19.7831 34.3164 22.9288 31.8192 22.6493 27.3463C22.5279 25.4026 21.5765 24.2554 20.0304 23.3734C18.5588 22.5339 16.6681 22.0021 14.5248 21.3992C11.9358 20.6711 8.93276 19.8532 6.62463 18.1522C3.85831 16.1136 1.96728 13.7505 2.6124 9.33333Z"/>
          </svg>
          OpenSearch
        </div>
        <div className="divider"></div>
        {(() => {
          // Ingestion tab is driven by a single server-computed flag
          // (show_ingestion_tab = local endpoint + local chunks). Search is
          // always the default view. uiMode "ingestion" is the launch-time
          // ingestion-only case, which hides search.
          const ingestionAvailable = showIngestionTab || uiMode === "ingestion";
          const searchAvailable = uiMode !== "ingestion";
          return (
            <div className="view-toggle-bar">
              {ingestionAvailable && (
                <button
                  className={`view-toggle-btn ${activeView === "ingestion" ? "active" : ""}`}
                  onClick={() => setActiveView("ingestion")}
                >
                  Ingestion
                </button>
              )}
              {searchAvailable && (
                <button className={`view-toggle-btn ${activeView === "search" ? "active" : ""}`} onClick={() => setActiveView("search")}>
                  Search
                </button>
              )}
            </div>
          );
        })()}
        <div className="topbar-right">
          <div className={`conn-badge ${backendConnected ? "connected" : "disconnected"}`}>
            <span className="conn-dot"></span>
            <strong>{backendConnected ? "Connected" : "Disconnected"}</strong>
            {backendEndpoint && <span className="conn-ep">{backendEndpoint}</span>}
          </div>
          <button className={`hdr-btn ${showSettings ? "on" : ""}`} onClick={() => setShowSettings(!showSettings)}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
            </svg>
            <span>Settings</span>
          </button>
        </div>
      </header>

      {showSettings && (
        <div className="settings-panel">
          {activeView === "ingestion" ? (
            /* Ingestion settings: chunk-set selection only. Field mapping,
               metadata, comparison, and template are search concepts and are
               intentionally hidden here. */
            <div className="idx-row">
              <div className="field-group">
                <label>Chunk</label>
                {ingestionIndexOptions.length > 0 ? (
                  <IndexDropdown
                    value={ingestionIndex || ingestionChunkIndex}
                    options={ingestionIndexOptions.map((o) => ({
                      name: o.name,
                      description: `${o.chunks} chunks`,
                    }))}
                    onChange={(v) => setIngestionIndex(v)}
                    placeholder="Select chunk set..."
                  />
                ) : (
                  <span className="idx-empty-note">No local chunk sets.</span>
                )}
              </div>
              <div className="spacer"></div>
              <div className="field-group">
                <label>Theme</label>
                <div className="theme-seg">
                  <button className={`theme-seg-btn ${!darkMode ? "active" : ""}`} onClick={() => setDarkMode(false)} aria-label="Light mode">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
                  </button>
                  <button className={`theme-seg-btn ${darkMode ? "active" : ""}`} onClick={() => setDarkMode(true)} aria-label="Dark mode">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
                  </button>
                </div>
              </div>
            </div>
          ) : (
          <>
          {/* Index / Size / View mode row */}
          {/* Search operates on cluster-backed indices only; chunk-only
              (source==="local") entries are inspectable in the Ingestion view,
              not searchable, so they're filtered out of the search pickers. */}
          <div className="idx-row">
            {searchableIndices.length >= 2 && activeTemplate !== "agent" && (
              <div className="field-group">
                <label>View</label>
                <ViewModeSelector
                enabled={comparisonEnabled}
                onToggle={(on) => {
                  if (on) {
                    setComparisonEnabled(true);
                    if (!compareIndex1 || !compareIndex2) {
                      const current = indexName.trim();
                      const names = searchableIndices.map((i) => i.name);
                      const other = names.find((n) => n !== current) || "";
                      if (!compareIndex1) setCompareIndex1(current || names[0] || "");
                      if (!compareIndex2) setCompareIndex2(other || names[1] || "");
                    }
                  } else {
                    setComparisonEnabled(false);
                    if (compareIndex1) {
                      setIndexName(compareIndex1);
                    }
                  }
                }}
              />
              </div>
            )}
            <div className="field-group">
              <label>Index</label>
              {searchableIndices.length > 0 ? (
                <IndexDropdown
                  value={comparisonEnabled ? compareIndex1 : indexName}
                  options={comparisonEnabled ? searchableIndices.filter((i) => i.name !== compareIndex2) : searchableIndices}
                  onChange={(v) => {
                    if (comparisonEnabled) {
                      setCompareIndex1(v);
                    } else {
                      setIndexName(v);
                      loadSuggestions(v);
                      fetchSchema(v);
                      setChatMessages([]);
                      setMemoryId(null);
                      // Clear the previous index's query text, results, and
                      // autocomplete so switching indices starts clean.
                      setQuery("");
                      setAutocompleteOptions([]);
                      setResults([]);
                      setStats("Ready");
                      setRagAnswer("");
                    }
                  }}
                  placeholder="Select index..."
                />
              ) : (
                <input className="idx-input" value={indexName} onChange={(e) => setIndexName(e.target.value)} placeholder="e.g. my-index" />
              )}
            </div>
            {comparisonEnabled && (
              <>
              <span className="vs-label">vs</span>
              <div className="field-group">
                <label>Index 2</label>
                <IndexDropdown
                  value={compareIndex2}
                  options={searchableIndices.filter((i) => i.name !== compareIndex1)}
                  onChange={(v) => { setCompareIndex2(v); loadSuggestions(v); fetchSchema(v); }}
                  placeholder="Select..."
                />
              </div>
              </>
            )}
            <div className="field-group">
              <label>Size</label>
              <input className="size-input" value={searchSize} onChange={(e) => setSearchSize(e.target.value)} />
            </div>
            <div className="spacer"></div>
            <div className="field-group">
              <label>Theme</label>
              <div className="theme-seg">
                <button
                  className={`theme-seg-btn ${!darkMode ? "active" : ""}`}
                  onClick={() => setDarkMode(false)}
                  aria-label="Light mode"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
                  </svg>
                </button>
                <button
                  className={`theme-seg-btn ${darkMode ? "active" : ""}`}
                  onClick={() => setDarkMode(true)}
                  aria-label="Dark mode"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
                  </svg>
                </button>
              </div>
            </div>
          </div>

          <div className="settings-section">
          <div className="sec-label">Template</div>
          <div className="tpl-grid">
            {TEMPLATES.map((t) => {
              const disabled = !!t.disabled;
              const isAgent = t.id === "agent";
              const isActive = activeTemplate === t.id;
              return (
                <div key={t.id} className={`tpl-card-wrap ${isAgent && isActive ? "expanded" : ""}`}>
                  <button
                    className={`tpl-card ${isActive ? "on" : ""} ${disabled ? "disabled" : ""}`}
                    disabled={disabled}
                    title=""
                    onClick={() => {
                      if (disabled) return;
                      handleTemplateChange(t.id);
                    }}
                  >
                    <div className="tpl-card-icon"><TemplateIcon id={t.id} /></div>
                    <div className="tpl-card-label">{t.label}</div>
                    {schema?.suggested_template === t.id && <span className="template-auto">auto</span>}
                  </button>
                  {isAgent && isActive && (
                    <div className="agent-mode-sub">
                      <button
                        className={`agent-mode-opt ${agenticMode === "search" ? "active" : ""} ${schema?.agentic_agent_type === "conversational" ? "disabled" : ""}`}
                        onClick={(e) => { e.stopPropagation(); if (schema?.agentic_agent_type !== "conversational") setAgenticMode("search"); }}
                        title={schema?.agentic_agent_type === "conversational" ? "Search requires a flow agent" : ""}
                      >
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                        Search
                        <span className="agent-mode-opt-desc">Answer + results</span>
                      </button>
                      <button
                        className={`agent-mode-opt ${agenticMode === "chat" ? "active" : ""} ${schema?.agentic_agent_type === "flow" ? "disabled" : ""}`}
                        onClick={(e) => { e.stopPropagation(); if (schema?.agentic_agent_type !== "flow") setAgenticMode("chat"); }}
                        title={schema?.agentic_agent_type === "flow" ? "Chat requires a conversational agent" : ""}
                      >
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                        Chat
                        <span className="agent-mode-opt-desc">Conversational</span>
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          </div>

          <div className="settings-section">
          {/* Field mapping */}
          <div className="field-map-row">
            <div className="field-map-group">
              <label>Title</label>
              <select value={titleField} onChange={(e) => setTitleField(e.target.value)}>
                <option>(none)</option>
                {textFields.map((f) => <option key={f}>{f}</option>)}
              </select>
            </div>
            <div className="field-map-group">
              <label>Description</label>
              <select value={descField} onChange={(e) => setDescField(e.target.value)}>
                <option>(none)</option>
                {textFields.map((f) => <option key={f}>{f}</option>)}
              </select>
            </div>
            <div className="field-map-group">
              <label>Image</label>
              <select value={imgField} onChange={(e) => setImgField(e.target.value)}>
                <option>(none)</option>
                {allFields.map((f) => <option key={f}>{f}</option>)}
              </select>
            </div>
          </div>
          </div>

          {/* Metadata chips */}
          {allFields.length > 0 && (
            <div className="meta-section">
              <div className="sec-label">Metadata</div>
              <div className="meta-chips">
                {allFields.map((f) => (
                  <button
                    key={f}
                    className={`meta-chip ${hiddenFields.has(f) ? "" : "selected"}`}
                    onClick={() => toggleHiddenField(f)}
                    title={hiddenFields.has(f) ? `${f} (hidden — click to show)` : `${f} (click to hide)`}
                  >{f}</button>
                ))}
              </div>
            </div>
          )}
          </>
          )}
        </div>
      )}

      {activeView === "ingestion" && (
        <section className="search-panel">
          {!backendEndpoint.includes("localhost") && backendEndpoint ? (
            <div className="ingestion-empty">
              <p>Ingestion preview is available on local only.</p>
              <p style={{fontSize: "11px", marginTop: "8px", color: "#999"}}>Switch to Search view to query the cloud index, or reconnect to localhost for chunk inspection.</p>
            </div>
          ) : (() => {
            // Ingestion view is a chunk-inspection add-on. It defaults to the
            // current index's resolved chunk set (same-name or provenance
            // parent), but the user may browse ANY chunk set cross-index.
            const effectiveIngestionIndex = ingestionIndex || ingestionChunkIndex;
            return (
              <>
                <IngestionView status={ingestionStatus} selectedIndex={effectiveIngestionIndex} />
              </>
            );
          })()}
        </section>
      )}

      {activeView === "search" && (
      <section className={`search-panel ${activeTemplate === "agent" && agenticMode === "chat" ? "chat-layout" : ""}`}>
            {/* Search bar and suggestions — hidden in chat mode */}
            {!(activeTemplate === "agent" && agenticMode === "chat") && (
            <>
            <div className="search-row">
              <div className="query-wrap">
                <span className="query-icon">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
                  </svg>
                </span>
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") { setAutocompleteOptions([]); runSearch(query); } }}
                  placeholder={activeTemplate === "agent" ? "Ask a question..." : "Search..."}
                />
                {autocompleteOptions.length > 0 && (
                  <div className="autocomplete-menu">
                    {autocompleteOptions.map((option) => (
                      <button key={option} type="button" className="autocomplete-option"
                        onMouseDown={(e) => e.preventDefault()} onClick={() => onAutocompleteOptionClick(option)}>
                        {option}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <button className="search-btn" onClick={() => runSearch(query)} disabled={loading}>
                {loading ? "..." : "Search"}
              </button>
            </div>

            {/* Suggestions */}
            <div className="suggestions">
              <div className="chips">
                {(activeTemplate === "agent"
                  ? (agentPrompts.search.length > 0 ? agentPrompts.search : (agentPromptsLoaded ? AGENT_PROMPTS_FALLBACK.search : [])).map((text) => ({ text, capability: "" }))
                  : suggestions.slice(0, 5)
                ).map((item) => (
                    <button key={`${item.text}-${item.capability || "none"}`} className="chip" onClick={() => {
                      if (activeTemplate === "agent") { setQuery(item.text); runSearch(item.text); }
                      else onSuggestionClick(item);
                    }}>
                      <span>{item.text}</span>
                      {item.capability && (
                        <span className={`cap-badge cap-${item.capability}`}>
                          {(capabilityLabel[item.capability] || item.capability).toUpperCase()}
                        </span>
                      )}
                    </button>
                  ))}
                </div>
            </div>
            </>
            )}

            {/* Results area: comparison view or standard single-index results */}
            {comparisonEnabled ? (
              <ComparisonView
                query={query}
                searchSize={searchSize}
                activeTemplate={activeTemplate}
                schema={schema}
                fieldOverrides={fieldOverrides}
                filterSource={filterSource}
                compareIndex1={compareIndex1}
                compareIndex2={compareIndex2}
              />
            ) : (
              <>
                {/* Status row — only shown after a search has been performed */}
                {(activeTemplate !== "agent" || agenticMode === "search") && results.length > 0 && (
                <div className="status-row">
                  <span>{stats}</span>
                  {queryMode && <span>mode: {queryMode}</span>}
                  {capability && <span>capability: {capability}</span>}
                  {activeTemplate !== "agent" && !error && <span>semantic: {usedSemantic ? "on" : "off"}</span>}
                  {error && <span className="error">{error}</span>}
                </div>
                )}

                {/* Agentic fallback warning — shown when agentic search failed or backend lacks agentic support */}
                {activeTemplate === "agent" && !loading && results.length > 0 && !ragAnswer && !agentStepsSummary && !dslQuery && (
                  <div className="agentic-fallback-warning">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                    <span>AI agent unavailable — showing standard search results.
                      {fallbackReason && fallbackReason.includes("expired") && " AWS credentials may have expired."}
                      {fallbackReason && fallbackReason.includes("timeout") && " The request timed out."}
                    </span>
                  </div>
                )}

                {/* Loading bar - hidden in agent chat mode (has typing indicator) */}
                {loading && (activeTemplate !== "agent" || agenticMode === "search") && (
                  <div className="loading-container">
                    <div className="loading-bar"><div className="loading-bar-progress"></div></div>
                    <div className="loading-text">Searching...</div>
                  </div>
                )}

                {/* Template-specific results */}
                {activeTemplate === "agent" && agenticMode === "chat" && (
                  <div className="chat-messages-area">
                    {chatMessages.length > 0 && (
                      <div className="chat-toolbar">
                        <button className="new-chat-btn" onClick={() => { setChatMessages([]); setMemoryId(null); }}>
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                          New conversation
                        </button>
                      </div>
                    )}
                    <AgenticChat messages={chatMessages} loading={loading} onPromptClick={(text) => { setQuery(text); runSearch(text); }} agentPrompts={agentPrompts} agentPromptsLoaded={agentPromptsLoaded} schema={schema} />
                    <div className="chat-input-bar">
                      <div className="query-wrap">
                        <span className="query-icon">
                          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
                          </svg>
                        </span>
                        <input
                          value={query}
                          onChange={(e) => setQuery(e.target.value)}
                          onKeyDown={(e) => { if (e.key === "Enter") { setAutocompleteOptions([]); runSearch(query); } }}
                          placeholder="Ask a question..."
                        />
                      </div>
                      <button className="search-btn" onClick={() => runSearch(query)} disabled={loading}>
                        {loading ? "..." : "Send"}
                      </button>
                    </div>
                  </div>
                )}
                {activeTemplate === "agent" && agenticMode === "search" && (
                  <>
                    {!loading && results.length === 0 && !ragAnswer && !error && (
                      <div className="chat-empty">
                        <div className="chat-empty-icon">
                          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" style={{opacity: 0.3}}>
                            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
                          </svg>
                        </div>
                        <div className="chat-empty-title">Agentic Search</div>
                        <div className="chat-empty-desc">Ask questions in natural language. The AI agent will decompose your query and find relevant results.</div>
                        <div className="chat-empty-examples">
                          Try: "Show me the most relevant results" or "Find items from the last 5 years"
                        </div>
                      </div>
                    )}
                    {ragAnswer && (
                      <div className="rag-answer-card">
                        <div className="rag-answer-text">{renderChatText(ragAnswer)}</div>
                      </div>
                    )}
                    {(agentStepsSummary || dslQuery) && results.length > 0 && (
                      <div className="search-reasoning-bar">
                        {agentStepsSummary && (
                          <details className="chat-agent-reasoning">
                            <summary>Agent reasoning</summary>
                            <div className="chat-reasoning-content">
                              <div className="chat-reasoning-section">
                                <pre className="chat-reasoning-pre">{agentStepsSummary}</pre>
                              </div>
                            </div>
                          </details>
                        )}
                        {dslQuery && (
                          <details className="chat-agent-reasoning">
                            <summary>Generated DSL</summary>
                            <div className="chat-reasoning-content">
                              <div className="chat-reasoning-section">
                                <pre className="chat-reasoning-pre">{(() => { try { return JSON.stringify(JSON.parse(dslQuery), null, 2); } catch(e) { return dslQuery; } })()}</pre>
                              </div>
                            </div>
                          </details>
                        )}
                      </div>
                    )}
                    {results.length > 0 && <DocumentResults results={results} loading={loading} filterSource={filterSource} schema={schema} fieldOverrides={fieldOverrides} />}
                  </>
                )}
                {activeTemplate === "document" && (
                  <>
                    {ragAnswer && (
                      <div className="rag-answer-card">
                        <div className="rag-answer-text">{renderChatText(ragAnswer)}</div>
                      </div>
                    )}
                    <DocumentResults results={results} loading={loading} filterSource={filterSource} schema={schema} fieldOverrides={fieldOverrides} />
                  </>
                )}
                {(activeTemplate === "ecommerce" || activeTemplate === "media") && (
                  <EcommerceResults results={results} loading={loading} schema={schema} fieldOverrides={fieldOverrides} filterSource={filterSource} />
                )}
              </>
            )}
      </section>
      )}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
