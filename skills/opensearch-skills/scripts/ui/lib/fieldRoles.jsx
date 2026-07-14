// Loaded as a classic <script type="text/babel"> in index.html; all UI
// files share one global scope (no bundler). Load order is defined there.

// ---------------------------------------------------------------------------
// Field role inference for ecommerce/media templates
// ---------------------------------------------------------------------------
const TITLE_HINTS = ["title", "name", "label", "heading", "subject", "primarytitle", "product", "item_name", "product_name", "headline"];
const IMAGE_HINTS = ["image", "img", "poster", "photo", "thumbnail", "picture", "cover", "avatar", "logo"];
const DESC_HINTS = ["description", "summary", "overview", "abstract", "content", "body", "text", "plot"];
const NOT_TITLE_HINTS = ["titletype", "type", "category", "kind"];
// Domain-emphasis hints. Order matters: compare-at/original checked before plain price.
const PRICE_HINTS = ["price", "amount", "cost", "msrp", "fare", "rate_usd", "list_price", "sale_price"];
const COMPARE_AT_HINTS = ["list_price", "msrp", "original_price", "was_price", "compare_at", "regular_price", "rrp"];
const RATING_HINTS = ["rating", "stars", "score_avg", "rating_avg", "average_rating", "avg_rating", "vote_average"];
const STOCK_HINTS = ["stock", "inventory", "qty", "quantity", "units_available", "in_stock", "available"];

function inferFieldRoles(source, schema, fieldOverrides) {
  const roles = { title: null, image: null, description: null, tags: [], metrics: [], price: null, compareAt: null, rating: null, stock: null };
  if (!source) return roles;

  // Apply user overrides first
  if (fieldOverrides) {
    if (fieldOverrides.title && fieldOverrides.title !== "(none)" && source[fieldOverrides.title] != null) {
      roles.title = { field: fieldOverrides.title, value: String(source[fieldOverrides.title]) };
    }
    if (fieldOverrides.description && fieldOverrides.description !== "(none)" && source[fieldOverrides.description] != null) {
      roles.description = { field: fieldOverrides.description, value: String(source[fieldOverrides.description]) };
    }
    if (fieldOverrides.image && fieldOverrides.image !== "(none)" && source[fieldOverrides.image] != null) {
      roles.image = { field: fieldOverrides.image, value: String(source[fieldOverrides.image]) };
    }
  }

  const fieldCategories = schema?.field_categories || {};
  const keywordFields = new Set(fieldCategories.keyword || []);
  const numericFields = new Set(fieldCategories.numeric || []);

  const isNumeric = (v) => typeof v === "number" || (typeof v === "string" && v.trim() !== "" && !isNaN(Number(v)));
  const numOf = (v) => (typeof v === "number" ? v : Number(v));

  for (const [key, val] of Object.entries(source)) {
    if (val == null || typeof val === "object") continue;
    const lower = key.toLowerCase();
    const strVal = String(val);

    if (!roles.title && TITLE_HINTS.some((h) => lower.includes(h)) && !NOT_TITLE_HINTS.some((h) => lower === h) && strVal.length < 200) {
      roles.title = { field: key, value: strVal };
      continue;
    }
    if (!roles.image && (IMAGE_HINTS.some((h) => lower.includes(h)) || /^https?:\/\/.+\.(jpe?g|png|gif|webp|svg)/i.test(strVal))) {
      roles.image = { field: key, value: strVal };
      continue;
    }
    if (!roles.description && DESC_HINTS.some((h) => lower.includes(h)) && strVal.length > 20) {
      roles.description = { field: key, value: strVal };
      continue;
    }
    // Domain emphasis roles. compare-at before price so list_price/msrp
    // aren't consumed as the sale price.
    if (!roles.compareAt && isNumeric(val) && COMPARE_AT_HINTS.some((h) => lower.includes(h))) {
      roles.compareAt = { field: key, value: numOf(val) };
      continue;
    }
    if (!roles.price && isNumeric(val) && PRICE_HINTS.some((h) => lower.includes(h))) {
      roles.price = { field: key, value: numOf(val) };
      continue;
    }
    if (!roles.rating && isNumeric(val) && RATING_HINTS.some((h) => lower.includes(h))) {
      roles.rating = { field: key, value: numOf(val) };
      continue;
    }
    if (!roles.stock && isNumeric(val) && STOCK_HINTS.some((h) => lower.includes(h))) {
      roles.stock = { field: key, value: numOf(val) };
      continue;
    }
    if (keywordFields.has(key) && strVal.length < 60) {
      roles.tags.push({ field: key, value: strVal });
    } else if (numericFields.has(key)) {
      roles.metrics.push({ field: key, value: val });
    }
  }

  // Fallback: use first short text as title, first long text as description
  if (!roles.title || !roles.description) {
    for (const [key, val] of Object.entries(source)) {
      if (val == null || typeof val === "object") continue;
      const strVal = String(val);
      if (!roles.title && strVal.length >= 3 && strVal.length < 120 && /[a-zA-Z]/.test(strVal)) {
        roles.title = { field: key, value: strVal };
      } else if (!roles.description && strVal.length > 40 && !/^https?:\/\//.test(strVal)) {
        roles.description = { field: key, value: strVal.slice(0, 300) };
      }
      if (roles.title && roles.description) break;
    }
  }

  return roles;
}
