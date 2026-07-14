// Loaded as a classic <script type="text/babel"> in index.html; all UI
// files share one global scope (no bundler). Load order is defined there.

// ---------------------------------------------------------------------------
// View Mode Selector (List / Compare)
// ---------------------------------------------------------------------------
function ViewModeSelector({ enabled, onToggle }) {
  return (
    <div className="view-mode-seg" role="radiogroup" aria-label="View mode">
      <button
        className={`view-mode-btn ${!enabled ? "active" : ""}`}
        onClick={() => onToggle(false)}
        role="radio"
        aria-checked={!enabled}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="3" y1="15" x2="21" y2="15"/>
        </svg>
        Single
      </button>
      <button
        className={`view-mode-btn ${enabled ? "active" : ""}`}
        onClick={() => onToggle(true)}
        role="radio"
        aria-checked={enabled}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="3" width="7" height="18" rx="1"/><rect x="14" y="3" width="7" height="18" rx="1"/>
        </svg>
        Compare
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ResultPane – one half of the comparison view
// ---------------------------------------------------------------------------
function ResultPane({ label, indexName, results, loading, error, stats, queryMode, capability, usedSemantic, fallbackReason, activeTemplate, schema, fieldOverrides, filterSource }) {
  const capabilityDesc = {
    exact: "Lexical BM25",
    semantic: "Semantic Vector",
    structured: "Structured Filter",
    combined: "Hybrid BM25 + Dense Vector",
    autocomplete: "Autocomplete",
    fuzzy: "Fuzzy Match",
    manual: "Manual Query",
  };

  const desc = capability ? (capabilityDesc[capability] || capability) : "";

  return (
    <div className="result-pane">
      <div className="result-pane-header">
        <span className="result-pane-name">{indexName || label}</span>
        {desc && <span className="result-pane-desc">{desc}</span>}
        <span className="result-pane-stats">{stats}</span>
      </div>

      {loading && (
        <div className="result-pane-loading">
          <div className="loading-bar"><div className="loading-bar-progress"></div></div>
          <span className="loading-text">Searching...</span>
        </div>
      )}

      {error && <div className="result-pane-error">{error}</div>}

      {!loading && !error && (
        <div className="result-pane-results">
          {activeTemplate === "ecommerce" || activeTemplate === "media" ? (
            <EcommerceResults results={results} loading={false} schema={schema} fieldOverrides={fieldOverrides} filterSource={filterSource} />
          ) : (
            <DocumentResults results={results} loading={false} filterSource={filterSource} schema={schema} fieldOverrides={fieldOverrides} />
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Comparison View — side-by-side search across two selected indices
// ---------------------------------------------------------------------------
function ComparisonView({ query, searchSize, activeTemplate, schema, fieldOverrides, filterSource, compareIndex1, compareIndex2 }) {
  // Index 1 pane state
  const [index1Results, setIndex1Results] = useState([]);
  const [index1Loading, setIndex1Loading] = useState(false);
  const [index1Error, setIndex1Error] = useState("");
  const [index1Stats, setIndex1Stats] = useState("Ready");
  const [index1QueryMode, setIndex1QueryMode] = useState("");
  const [index1Capability, setIndex1Capability] = useState("");
  const [index1UsedSemantic, setIndex1UsedSemantic] = useState(false);
  const [index1FallbackReason, setIndex1FallbackReason] = useState("");

  // Index 2 pane state
  const [index2Results, setIndex2Results] = useState([]);
  const [index2Loading, setIndex2Loading] = useState(false);
  const [index2Error, setIndex2Error] = useState("");
  const [index2Stats, setIndex2Stats] = useState("Ready");
  const [index2QueryMode, setIndex2QueryMode] = useState("");
  const [index2Capability, setIndex2Capability] = useState("");
  const [index2UsedSemantic, setIndex2UsedSemantic] = useState(false);
  const [index2FallbackReason, setIndex2FallbackReason] = useState("");

  // Request sequence ID to prevent stale results from overwriting newer ones
  const requestIdRef = useRef(0);

  const runComparisonSearch = async (queryText) => {
    const thisRequest = ++requestIdRef.current;
    setIndex1Loading(true);
    setIndex2Loading(true);
    setIndex1Error("");
    setIndex2Error("");

    const makeRequest = (indexName) => {
      const qs = new URLSearchParams();
      qs.set("index", indexName);
      qs.set("q", queryText);
      qs.set("size", String(searchSize));
      qs.set("debug", "1");
      return fetch(`/api/search?${qs.toString()}`).then(r => r.json());
    };

    const [result1, result2] = await Promise.allSettled([
      makeRequest(compareIndex1),
      makeRequest(compareIndex2),
    ]);

    // Discard results if a newer request has been fired
    if (thisRequest !== requestIdRef.current) return;

    // Handle index 1 result
    if (result1.status === "fulfilled") {
      const data = result1.value;
      if (data.error) {
        setIndex1Error(data.error);
        setIndex1Results([]);
      } else {
        setIndex1Results(data.hits || []);
        setIndex1Stats(`${data.total ?? 0} hits — ${data.took_ms ?? 0}ms`);
        setIndex1QueryMode(data.query_mode || "");
        setIndex1Capability(data.capability || "");
        setIndex1UsedSemantic(Boolean(data.used_semantic));
        setIndex1FallbackReason(data.fallback_reason || "");
      }
    } else {
      setIndex1Error(result1.reason?.message || "Request failed");
      setIndex1Results([]);
    }
    setIndex1Loading(false);

    // Handle index 2 result
    if (result2.status === "fulfilled") {
      const data = result2.value;
      if (data.error) {
        setIndex2Error(data.error);
        setIndex2Results([]);
      } else {
        setIndex2Results(data.hits || []);
        setIndex2Stats(`${data.total ?? 0} hits — ${data.took_ms ?? 0}ms`);
        setIndex2QueryMode(data.query_mode || "");
        setIndex2Capability(data.capability || "");
        setIndex2UsedSemantic(Boolean(data.used_semantic));
        setIndex2FallbackReason(data.fallback_reason || "");
      }
    } else {
      setIndex2Error(result2.reason?.message || "Request failed");
      setIndex2Results([]);
    }
    setIndex2Loading(false);
  };

  // Trigger search when query, searchSize, or compared indices change
  useEffect(() => {
    if (query && query.trim()) {
      runComparisonSearch(query.trim());
    }
  }, [query, searchSize, compareIndex1, compareIndex2]);

  return (
    <div>
      {/* Side-by-side result panes */}
      <div className="comparison-panes">
        <ResultPane
          label="Index 1"
          indexName={compareIndex1}
          results={index1Results}
          loading={index1Loading}
          error={index1Error}
          stats={index1Stats}
          queryMode={index1QueryMode}
          capability={index1Capability}
          usedSemantic={index1UsedSemantic}
          fallbackReason={index1FallbackReason}
          activeTemplate={activeTemplate}
          schema={schema}
          fieldOverrides={fieldOverrides}
          filterSource={filterSource}
        />
        <ResultPane
          label="Index 2"
          indexName={compareIndex2}
          results={index2Results}
          loading={index2Loading}
          error={index2Error}
          stats={index2Stats}
          queryMode={index2QueryMode}
          capability={index2Capability}
          usedSemantic={index2UsedSemantic}
          fallbackReason={index2FallbackReason}
          activeTemplate={activeTemplate}
          schema={schema}
          fieldOverrides={fieldOverrides}
          filterSource={filterSource}
        />
      </div>
    </div>
  );
}
