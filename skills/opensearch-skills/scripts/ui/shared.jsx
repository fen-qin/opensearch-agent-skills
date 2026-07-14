// Loaded as a classic <script type="text/babel"> in index.html; all UI
// files share one global scope (no bundler). Load order is defined there.

const { useEffect, useState, useRef, useCallback, useMemo } = React;

const TEMPLATES = [
  { id: "document", label: "Document" },
  { id: "ecommerce", label: "E-Commerce" },
  { id: "agent", label: "Agent" },
];

const AGENT_PROMPTS_FALLBACK = {
  search: [
    "Find items with high ratings from recent years",
    "Show me entries in a specific category",
    "Top results matching a keyword",
    "Items with particular attributes or filters",
  ],
  chat: [
    "What are the highest rated items?",
    "Tell me about the most popular categories",
    "Recommend something interesting",
    "Which items stand out in this collection?",
  ],
};
