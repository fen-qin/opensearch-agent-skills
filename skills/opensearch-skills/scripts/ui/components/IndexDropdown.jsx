// Loaded as a classic <script type="text/babel"> in index.html; all UI
// files share one global scope (no bundler). Load order is defined there.

// ---------------------------------------------------------------------------
// Custom Dropdown for version/index selection
// ---------------------------------------------------------------------------
function IndexDropdown({ value, options, onChange, placeholder }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const handleClick = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const selected = options.find((o) => o.name === value);

  return (
    <div className="idx-dropdown" ref={ref}>
      <button className="idx-dropdown-trigger" onClick={() => setOpen(!open)} type="button">
        <span className="idx-dropdown-value">{selected ? selected.name : (placeholder || "Select...")}</span>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M6 9l6 6 6-6"/>
        </svg>
      </button>
      {open && (
        <div className="idx-dropdown-menu">
          {options.map((opt) => (
            <button
              key={opt.name}
              className={`idx-dropdown-item ${opt.name === value ? "selected" : ""}`}
              onClick={() => { onChange(opt.name); setOpen(false); }}
              type="button"
            >
              <div className="idx-dropdown-item-name">{opt.name}</div>
              <div className="idx-dropdown-item-meta">
                {opt.source === "local" ? `local chunks · ${opt.profile || "chunks"}`
                  : opt.source === "both" ? `cluster + local${opt.profile ? " · " + opt.profile : ""}`
                  : (opt.description || `${opt.docs} docs`)}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
