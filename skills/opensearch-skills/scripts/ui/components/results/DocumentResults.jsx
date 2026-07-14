// Loaded as a classic <script type="text/babel"> in index.html; all UI
// files share one global scope (no bundler). Load order is defined there.

// ---------------------------------------------------------------------------
// Template: Document Search (list with large previews, score bars)
// ---------------------------------------------------------------------------
function DocumentResults({ results, loading, filterSource, schema, fieldOverrides }) {
  if (loading) return null;
  return (
    <div className="results doc-results">
      {results.map((item, idx) => {
        const s = item.source || {};
        const displaySource = filterSource ? filterSource(s) : s;
        const roles = inferFieldRoles(displaySource, schema, fieldOverrides);
        const title = roles.title?.value || item.preview || "Untitled";
        const metaParts = [];
        roles.tags.slice(0, 3).forEach((tag) => metaParts.push(tag.value));
        roles.metrics.slice(0, 2).forEach((m) => metaParts.push(`${m.field}: ${m.value}`));
        const metaLine = metaParts.join(" · ");
        const score = Number(item.score || 0).toFixed(4);
        // Citation: surface source document, page, and section when present.
        const docName = s.doc_name || s.source_name || s.document || s.file_name || s.filename || "";
        const pageNum = s.page_number ?? s.page ?? s.page_no ?? null;
        const headingsArr = Array.isArray(s.headings) ? s.headings : null;
        const section = (headingsArr && headingsArr.length ? headingsArr[headingsArr.length - 1] : (s.section || s.heading || ""));
        const hasCitation = docName || pageNum != null || section;
        // Snippet: show a text preview prominently rather than only in details.
        const snippet = roles.description?.value || item.preview || "";
        const snippetText = snippet && snippet !== title ? String(snippet).slice(0, 320) : "";
        return (
          <article className="doc-card" key={item.id || idx} style={{ animationDelay: `${idx * 35}ms` }}>
            <span className="doc-rank">{idx + 1}</span>
            <div className="doc-content">
              <div className="doc-title-row">
                <span className="doc-title">{title}</span>
                <span className="doc-score-badge" title="relevance score">{score}</span>
              </div>
              {hasCitation && (
                <div className="doc-citation">
                  {docName && <span className="doc-cite-doc">{docName}</span>}
                  {pageNum != null && <span className="doc-cite-page">p.{pageNum}</span>}
                  {section && <span className="doc-cite-section">{section}</span>}
                </div>
              )}
              {snippetText && <div className="doc-snippet">{snippetText}</div>}
              {metaLine && <div className="doc-meta">{metaLine}</div>}
              <div className="doc-details-row">
                <details className="doc-details">
                <summary>View details</summary>
                <div className="doc-details-content">
                  <div className="doc-detail-row"><span className="doc-detail-label">ID:</span> <code>{item.id || "(none)"}</code></div>
                  <pre>{JSON.stringify(displaySource, null, 2)}</pre>
                </div>
              </details>
              </div>
            </div>
          </article>
        );
      })}
    </div>
  );
}
