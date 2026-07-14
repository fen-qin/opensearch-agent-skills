// Loaded as a classic <script type="text/babel"> in index.html; all UI
// files share one global scope (no bundler). Load order is defined there.

// ---------------------------------------------------------------------------
// Template: Ecommerce (grid cards with images, tags, metrics)
// ---------------------------------------------------------------------------
function EcommerceResults({ results, loading, schema, fieldOverrides, filterSource }) {
  if (loading) return null;
  return (
    <div className="ecommerce-grid">
      {results.map((item, idx) => {
        const displaySource = filterSource ? filterSource(item.source) : item.source;
        const roles = inferFieldRoles(displaySource, schema, fieldOverrides);
        // Domain emphasis: discount, low stock.
        const price = roles.price?.value;
        const compareAt = roles.compareAt?.value;
        const hasDiscount = typeof price === "number" && typeof compareAt === "number" && compareAt > price;
        const saveAmt = hasDiscount ? compareAt - price : 0;
        const savePct = hasDiscount ? Math.round((saveAmt / compareAt) * 100) : 0;
        const rating = roles.rating?.value;
        const stock = roles.stock?.value;
        const lowStock = typeof stock === "number" && stock > 0 && stock < 5;
        const fmtPrice = (n) => (Number.isInteger(n) ? `$${n}` : `$${n.toFixed(2)}`);
        return (
          <article className="ecommerce-card" key={item.id || idx} style={{ animationDelay: `${idx * 40}ms` }}>
            {roles.image && (
              <div className="ecommerce-image">
                {hasDiscount && <span className="ecommerce-deal-badge">Save {fmtPrice(saveAmt)} (-{savePct}%)</span>}
                <img src={roles.image.value} alt="" loading="lazy" onError={(e) => { e.target.style.display = "none"; }} />
              </div>
            )}
            <div className="ecommerce-body">
              <div className="ecommerce-title-row">
                <span className="ecommerce-rank">{idx + 1}</span>
                <span className="ecommerce-title">{roles.title?.value || item.preview || item.id}</span>
              </div>
              {roles.description && roles.description.value !== (roles.title?.value || "") && (
                <div className="ecommerce-desc">{roles.description.value}</div>
              )}
              {(typeof price === "number" || typeof rating === "number" || lowStock) && (
                <div className="ecommerce-emphasis">
                  {typeof price === "number" && (
                    <span className="ecommerce-price">
                      {hasDiscount && <s className="ecommerce-price-was">{fmtPrice(compareAt)}</s>}
                      <strong>{fmtPrice(price)}</strong>
                    </span>
                  )}
                  {typeof rating === "number" && (
                    <span className="ecommerce-rating" title={roles.rating.field}>★ {rating.toFixed(1)}</span>
                  )}
                  {lowStock && <span className="ecommerce-lowstock">Only {stock} left</span>}
                </div>
              )}
              {roles.tags.length > 0 && (
                <div className="ecommerce-tags">
                  {roles.tags.slice(0, 5).map((tag) => (
                    <span key={tag.field} className="ecommerce-tag" title={tag.field}>{tag.value}</span>
                  ))}
                </div>
              )}
              <div className="ecommerce-footer">
                {roles.metrics.slice(0, 3).map((m) => (
                  <span key={m.field} className="ecommerce-metric" title={m.field}>
                    {m.field}: <strong>{m.value}</strong>
                  </span>
                ))}
                <span className="score">score {Number(item.score || 0).toFixed(3)}</span>
              </div>
            </div>
          </article>
        );
      })}
    </div>
  );
}
