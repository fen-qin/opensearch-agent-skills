// Loaded as a classic <script type="text/babel"> in index.html; all UI
// files share one global scope (no bundler). Load order is defined there.

// ---------------------------------------------------------------------------
// Ingestion View — componentized (data hook + focused sub-components) to keep
// per-index state isolated and avoid the stale-global-status / hook-order bugs.
// ---------------------------------------------------------------------------

// Hook: owns per-index ingestion data fetch + derived values. Never reads global
// ingestion status for per-index display.
function useIngestionData(selectedIndex) {
  const [chunkData, setChunkData] = useState(null);
  const [fetchError, setFetchError] = useState(null);

  useEffect(() => {
    if (!selectedIndex) { setChunkData(null); setFetchError(null); return; }
    let cancelled = false;
    setChunkData(null);
    setFetchError(null);
    fetch(`/api/ingestion-chunks?index=${encodeURIComponent(selectedIndex)}`)
      .then(r => {
        if (!r.ok) throw new Error(`Failed to load chunks (HTTP ${r.status})`);
        return r.json();
      })
      .then(data => {
        if (!cancelled) {
          if (data.error) { setFetchError(data.error); setChunkData(null); }
          else setChunkData(data);
        }
      })
      .catch(err => { if (!cancelled) setFetchError(err.message || "Failed to load ingestion data"); });
    return () => { cancelled = true; };
  }, [selectedIndex]);

  const chunks = useMemo(() => chunkData?.chunks || [], [chunkData]);
  const totalPages = useMemo(() => {
    if (!chunks.length) return 1;
    return Math.max(1, ...chunks.map(c => c.page_number || 1));
  }, [chunks]);

  return { chunkData, chunks, totalPages, fetchError };
}

// Leaf: objective per-profile processing signals + coverage note.
function ProcessingSignals({ chunkData }) {
  const summary = chunkData.summary || {};
  const profile = chunkData.profile;
  const cov = summary.coverage;
  const pages = chunkData.source_pages;
  const avgTok = summary.tokens_avg_est ?? summary.avg_tokens;
  const sizeOk = avgTok >= 64 && avgTok <= 700;
  const showCov = ["semantic", "multimodal"].includes(profile);
  const rows = [];
  if (profile === "semantic") {
    rows.push({ ok: sizeOk, label: `${chunkData.total} chunks, ~${Math.round(avgTok)} tokens each` });
    rows.push({ ok: (summary.pct_chunks_with_headings || 0) >= 50, label: `${summary.pct_chunks_with_headings ?? 0}% of chunks keep heading context` });
  } else if (profile === "tables") {
    rows.push({ ok: summary.chunks_with_tables > 0, label: summary.chunks_with_tables > 0 ? `Tables extracted in ${summary.chunks_with_tables} chunk(s)` : "No tables extracted" });
    rows.push({ ok: chunkData.total > 0, label: `${chunkData.total} chunks (table cells serialized into text)` });
  } else if (profile === "multimodal") {
    rows.push({ ok: summary.chunks_with_image_descriptions > 0, label: summary.chunks_with_image_descriptions > 0 ? `${summary.chunks_with_image_descriptions} image(s) described (approximate)` : "No images described" });
    rows.push({ ok: chunkData.total > 0, label: `${chunkData.total} chunks` });
  } else if (profile === "scanned") {
    rows.push({ ok: chunkData.total > 0, label: `OCR produced text — ${chunkData.total} chunk(s)` });
  } else {
    rows.push({ ok: chunkData.total > 0, label: `${chunkData.total} chunks` });
  }
  return (
    <>
      <div className="quality-section-title">Processing signals</div>
      <div className="quality-signals">
        {rows.map((r, i) => (
          <div key={i} className={`quality-signal ${r.ok ? "ok" : "warn"}`}>
            <span className="signal-mark">{r.ok ? "✓" : "—"}</span> {r.label}
          </div>
        ))}
      </div>
      {showCov && typeof cov === "number" && (
        <div className="quality-coverage">
          Captured {Math.round(cov * 100)}% of the extractable text{pages ? ` from the ${pages} processed page(s)` : ""}.
          {cov < 0.6 ? " Low coverage often means content lives in figures/tables — try the multimodal or tables profile." : ""}
        </div>
      )}
    </>
  );
}

// Leaf: cached agent (LLM) quality verdict, or a "not yet judged" prompt.
function VerdictCard({ verdict, selectedIndex }) {
  const labels = { great: "Great", good: "Good", fair: "Fair", needs_attention: "Needs attention" };
  if (!verdict) {
    return (
      <div className="quality-unjudged">
        Not yet judged. Ask the agent to evaluate quality (it runs <code>eval-document --index {selectedIndex}</code>, reviews the chunks, then saves a verdict).
      </div>
    );
  }
  return (
    <div className="quality-verdict-block">
      <div className="quality-section-title">
        Quality verdict <span className={`verdict-pill verdict-${verdict.overall}`}>{labels[verdict.overall] || verdict.overall}</span>
        <span className="verdict-by">judged by agent</span>
      </div>
      {verdict.summary && <div className="verdict-summary">{verdict.summary}</div>}
      {Array.isArray(verdict.dimensions) && (
        <div className="verdict-dims">
          {verdict.dimensions.map((d, i) => (
            <div key={i} className={`verdict-dim dim-${d.rating}`}>
              <span className="dim-rating">{d.rating}</span>
              <span className="dim-name">{(d.name || "").replace(/_/g, " ")}</span>
              {d.note && <span className="dim-note">— {d.note}</span>}
            </div>
          ))}
        </div>
      )}
      {Array.isArray(verdict.recommendations) && verdict.recommendations.length > 0 && (
        <ul className="verdict-recs">
          {verdict.recommendations.map((rec, i) => <li key={i}>{rec}</li>)}
        </ul>
      )}
    </div>
  );
}

// Leaf: chunk-size histogram.
function ChunkSizeHistogram({ histogram }) {
  const keys = Object.keys(histogram || {});
  if (keys.length === 0) return null;
  const max = Math.max(...Object.values(histogram), 1);
  return (
    <div className="ingestion-histogram">
      <div className="hist-title">Chunk Size Distribution (tokens)</div>
      {Object.entries(histogram).map(([range, count]) => (
        <div key={range} className="hist-row">
          <span className="hist-label">{range}</span>
          <div className="hist-bar-bg"><div className="hist-bar-fill" style={{ width: `${(count / max) * 100}%` }} /></div>
          <span className="hist-count">{count}</span>
        </div>
      ))}
    </div>
  );
}

// Leaf: per-index source file card (reads chunkData, never global status).
function SourceFileCard({ chunkData, selectedIndex }) {
  return (
    <div className="ingestion-card">
      <div className="ingestion-card-header"><h3>Source File</h3></div>
      <div className="ingestion-files">
        <div className="ingestion-file">
          <div className="ingestion-file-icon">PDF</div>
          <div className="ingestion-file-info">
            <div className="ingestion-file-name">{chunkData.source_name || selectedIndex}</div>
            <div className="ingestion-file-meta">
              {chunkData.source_pages ? `${chunkData.source_pages} pages · ` : ""}{chunkData.total} chunks · {chunkData.profile} profile
            </div>
          </div>
          <span className="ingestion-file-badge badge-chunks_ready">Ready</span>
        </div>
      </div>
    </div>
  );
}

// Leaf: pure list of chunks for the current page.
function ChunkList({ pageChunks, selectedChunkIdx, onSelect }) {
  if (pageChunks.length === 0) {
    return <div className="no-chunks-msg">No chunks extracted from this page</div>;
  }
  return (
    <>
      {pageChunks.map((chunk, i) => (
        <div key={chunk.chunk_id ?? i} className={`page-chunk-card ${i === selectedChunkIdx ? "selected" : ""}`} onClick={() => onSelect(i)}>
          <div className="page-chunk-header">
            <span className="chunk-tag">#{chunk.chunk_id}</span>
            {chunk.headings?.length > 0 && <span className="chunk-tag section-tag">{chunk.headings[chunk.headings.length - 1]}</span>}
            <span className="chunk-tag">{Math.max(1, Math.round((chunk.text?.length || 0) / 4))} tok</span>
            {chunk.has_tables && <span className="chunk-tag">table</span>}
            {chunk.has_image_descriptions && <span className="chunk-tag">image</span>}
          </div>
          <div className="page-chunk-text">{chunk.text}</div>
        </div>
      ))}
    </>
  );
}

// PDF preview canvas — owns the pdf.js lifecycle only. totalPages comes from the
// chunk data (prop), so paging works even if pdf.js fails to load.
function PdfPreview({ selectedIndex, currentPage, highlightChunk }) {
  const [pdfDoc, setPdfDoc] = useState(null);
  const canvasRef = useRef(null);

  useEffect(() => {
    if (!selectedIndex) return;
    let cancelled = false;
    setPdfDoc(null);
    const loadPdf = async () => {
      try {
        const pdf = await window.pdfjsLib.getDocument(`/api/pdf-file?index=${encodeURIComponent(selectedIndex)}`).promise;
        if (!cancelled) setPdfDoc(pdf);
      } catch (e) {
        if (!cancelled) console.warn("PDF load failed for index:", selectedIndex, e);
      }
    };
    let waitId = null;
    if (window.pdfjsLib) loadPdf();
    else waitId = setInterval(() => { if (window.pdfjsLib) { clearInterval(waitId); waitId = null; if (!cancelled) loadPdf(); } }, 200);
    return () => { cancelled = true; if (waitId) clearInterval(waitId); };
  }, [selectedIndex]);

  useEffect(() => {
    if (!pdfDoc || !canvasRef.current) return;
    let cancelled = false;
    (async () => {
      const page = await pdfDoc.getPage(currentPage);
      if (cancelled || !canvasRef.current) return;
      const canvas = canvasRef.current;
      const ctx = canvas.getContext("2d");
      const viewport = page.getViewport({ scale: 1 });
      const scale = Math.min(450 / viewport.width, 600 / viewport.height);
      const scaledViewport = page.getViewport({ scale });
      canvas.width = scaledViewport.width;
      canvas.height = scaledViewport.height;
      await page.render({ canvasContext: ctx, viewport: scaledViewport }).promise;
      if (highlightChunk && highlightChunk.bboxes) {
        const pageBboxes = highlightChunk.bboxes.filter(b => b.page === currentPage);
        ctx.fillStyle = "rgba(26, 115, 232, 0.15)";
        ctx.strokeStyle = "rgba(26, 115, 232, 0.6)";
        ctx.lineWidth = 1.5;
        for (const bbox of pageBboxes) {
          const x = bbox.l * scale;
          const y = (viewport.height - bbox.t) * scale;
          const w = (bbox.r - bbox.l) * scale;
          const h = (bbox.t - bbox.b) * scale;
          ctx.fillRect(x, y, w, h);
          ctx.strokeRect(x, y, w, h);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [pdfDoc, currentPage, highlightChunk]);

  return <canvas ref={canvasRef} className="pdf-canvas" />;
}

function IngestionView({ status, selectedIndex }) {
  const { chunkData, chunks, totalPages, fetchError } = useIngestionData(selectedIndex);
  const [selectedChunkIdx, setSelectedChunkIdx] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);

  // Reset paging/selection when the index changes.
  useEffect(() => { setCurrentPage(1); setSelectedChunkIdx(0); }, [selectedIndex]);
  // Reset selection when page changes so it stays valid.
  useEffect(() => { setSelectedChunkIdx(0); }, [currentPage]);

  const pageChunks = useMemo(
    () => chunks.filter(c => (c.page_number || 1) === currentPage),
    [chunks, currentPage]
  );

  // Show the "no data" prompt only when there's neither a live/last ingestion
  // status NOR any chunks for the selected set. With provenance + cross-index
  // browsing, chunkData (per-index) is the source of truth; the global status
  // may be stale or absent in a fresh session even though chunks exist.
  const hasChunkData = chunkData && chunkData.total > 0;
  if (fetchError) {
    return (
      <div className="ingestion-empty">
        <p className="ingestion-error">Error loading ingestion data: {fetchError}</p>
      </div>
    );
  }
  if (!hasChunkData && (!status || (!status.active && !status.stage))) {
    return (
      <div className="ingestion-empty">
        <p>No ingestion data. Start ingestion via agent conversation.</p>
      </div>
    );
  }

  if (chunkData && chunkData.total === 0 && !status?.active) {
    return (
      <div className="ingestion-view">
        <div className="ingestion-empty">
          <p>No chunks for index "{selectedIndex || "—"}".</p>
          <p style={{fontSize: "11px", marginTop: "8px", color: "#999"}}>This index was not processed via the ingest command. Only PDF/DOCX files processed with Docling appear here.</p>
        </div>
      </div>
    );
  }

  const totals = status?.totals || {};
  // A live ingest is only relevant to THIS view if it's for the selected index.
  const liveForThisIndex = Boolean(status?.active && status?.index && status.index === selectedIndex);
  const stage = liveForThisIndex ? (status?.stage || "processing")
    : (chunkData?.total > 0 ? "chunks_ready" : (status?.stage || "unknown"));
  const summary = chunkData?.summary || {};
  const hasData = chunkData?.total > 0;

  return (
    <div className="ingestion-view">
      <div className="ingestion-card">
        <div className="ingestion-card-header">
          <h3>Ingestion</h3>
          {chunkData?.profile && <span className="ingestion-profile-badge">{chunkData.profile}</span>}
          <span className={`ingestion-badge ${liveForThisIndex ? "badge-active" : stage === "chunks_ready" ? "badge-ready" : "badge-error"}`}>
            {liveForThisIndex ? "Processing..." : stage === "chunks_ready" ? "Chunks Ready" : stage === "error" ? "Error" : stage}
          </span>
        </div>

        <div className="ingestion-progress">
          <div className="ingestion-progress-bar">
            <div className={`ingestion-progress-fill ${liveForThisIndex ? "indeterminate" : ""}`} style={{ width: "100%" }} />
          </div>
          {chunkData?.source_name && (
            <div className="ingestion-progress-text">
              <span>{chunkData.source_name}{chunkData.source_pages ? ` (${chunkData.source_pages} pages)` : ""}</span>
              <span>{liveForThisIndex ? "Processing..." : "Done"}</span>
            </div>
          )}
        </div>

        {hasData && (
          <div className="ingestion-metrics">
            <div className="ingestion-metric"><span className="metric-value">{chunkData.total}</span><span className="metric-label">Chunks</span></div>
            <div className="ingestion-metric"><span className="metric-value">{summary.avg_tokens || "—"}</span><span className="metric-label">Avg Tokens</span></div>
            <div className="ingestion-metric"><span className="metric-value">{summary.sections || "—"}</span><span className="metric-label">Sections</span></div>
            <div className="ingestion-metric"><span className="metric-value">{totals.errors || 0}</span><span className="metric-label">Errors</span></div>
          </div>
        )}

        {hasData && (
          <div className="ingestion-quality">
            <ProcessingSignals chunkData={chunkData} />
            <VerdictCard verdict={chunkData.verdict} selectedIndex={selectedIndex} />
          </div>
        )}

        <ChunkSizeHistogram histogram={chunkData?.histogram} />
      </div>

      {hasData && <SourceFileCard chunkData={chunkData} selectedIndex={selectedIndex} />}

      {chunks.length > 0 && (
        <div className="ingestion-card">
          <div className="ingestion-card-header">
            <h3>Document Preview</h3>
            <span className="chunk-nav">
              <button disabled={currentPage <= 1} onClick={() => setCurrentPage(p => p - 1)}>&laquo;</button>
              <span>Page {currentPage} of {totalPages}</span>
              <button disabled={currentPage >= totalPages} onClick={() => setCurrentPage(p => p + 1)}>&raquo;</button>
            </span>
          </div>
          <div className="pdf-chunks-sidebyside">
            <div className="pdf-page-panel">
              <div className="panel-label">Source</div>
              <PdfPreview selectedIndex={selectedIndex} currentPage={currentPage} highlightChunk={pageChunks[selectedChunkIdx]} />
            </div>
            <div className="chunks-from-page-panel">
              <div className="panel-label">Extracted Chunks</div>
              <ChunkList pageChunks={pageChunks} selectedChunkIdx={selectedChunkIdx} onSelect={setSelectedChunkIdx} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
