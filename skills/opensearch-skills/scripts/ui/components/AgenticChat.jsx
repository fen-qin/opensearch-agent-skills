// Loaded as a classic <script type="text/babel"> in index.html; all UI
// files share one global scope (no bundler). Load order is defined there.

// ---------------------------------------------------------------------------
// Template: Agentic Chat
// ---------------------------------------------------------------------------
// Generate a conversational summary from search results
function generateChatSummary(query, results, total, schema) {
  if (!results || results.length === 0) {
    return `I couldn't find any results matching "${query}". Try rephrasing your question or using different keywords.`;
  }

  const count = total ?? results.length;
  const topItems = results.slice(0, 5);

  let summary = `I found ${count} result${count !== 1 ? "s" : ""} for your query. `;

  if (count <= 3) {
    summary += `Here's what I found:\n\n`;
  } else {
    summary += `Here are the top matches:\n\n`;
  }

  topItems.forEach((item, i) => {
    const s = item.source || {};
    const roles = inferFieldRoles(s, schema, null);
    const title = roles.title?.value || item.preview || "Untitled";
    const score = Number(item.score || 0);
    const tags = roles.tags.slice(0, 2).map((t) => t.value).join(", ");
    const tagsStr = tags ? ` ${"\u2022"} ${tags}` : "";

    summary += `${i + 1}. **${title}**`;
    summary += `${tagsStr}`;
    if (score > 0) summary += ` ${"\u2022"} Relevance: ${score.toFixed(2)}`;
    summary += `\n`;
    if (roles.description && roles.description.value !== title) {
      const shortDesc = roles.description.value.length > 150 ? roles.description.value.slice(0, 147) + "..." : roles.description.value;
      summary += `   ${shortDesc}\n`;
    }
    summary += `\n`;
  });

  if (count > 5) {
    summary += `...and ${count - 5} more result${count - 5 !== 1 ? "s" : ""}.`;
  }

  return summary;
}

// Simple markdown-like rendering (bold only)
function renderChatText(text) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    return part;
  });
}

function AgenticChat({ messages, loading, onPromptClick, agentPrompts, agentPromptsLoaded, schema }) {
  const endRef = useRef(null);
  useEffect(() => {
    if (messages.length > 0) endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  return (
    <div className="chat-messages">
      {messages.length === 0 && (
        <div className="chat-empty">
          <div className="chat-empty-icon">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" style={{opacity: 0.3}}>
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
            </svg>
          </div>
          <div className="chat-empty-title">Conversational Search</div>
          <div className="chat-empty-desc">Ask follow-up questions and the agent will remember the context of your conversation.</div>
          <div className="suggested-prompts">
            {(agentPrompts?.chat?.length > 0 ? agentPrompts.chat : (agentPromptsLoaded ? AGENT_PROMPTS_FALLBACK.chat : [])).map((p) => (
              <button key={p} className="suggested-prompt" onClick={() => onPromptClick && onPromptClick(p)}>{p}</button>
            ))}
          </div>
        </div>
      )}
      {messages.map((msg, idx) => (
        <div key={idx} className={`chat-bubble chat-${msg.role}`}>
          {msg.role === "user" ? (
            <div className="chat-user-text">{msg.text}</div>
          ) : (
            <div className="chat-assistant">
              {msg.results && msg.results.length > 0 ? (
                <>
                  {msg.agent_steps_summary && (
                    <details className="chat-agent-reasoning" open>
                      <summary>Agent reasoning</summary>
                      <div className="chat-reasoning-content">
                        <div className="chat-reasoning-section">
                          <div className="chat-reasoning-label">Steps</div>
                          <pre className="chat-reasoning-pre">{msg.agent_steps_summary}</pre>
                        </div>
                      </div>
                    </details>
                  )}
                  <div className="chat-summary">
                    {renderChatText(msg.summary || generateChatSummary(msg.query, msg.results, msg.total, schema))}
                  </div>
                  <div className="chat-meta-bar">
                    <span>{msg.total ?? msg.results.length} result(s) {"\u2022"} {msg.took_ms ?? 0}ms</span>
                    {msg.capability && <span className="chat-cap-badge">{msg.capability}</span>}
                  </div>
                  <details className="chat-sources">
                    <summary>View source documents ({msg.results.length})</summary>
                    <div className="chat-source-list">
                      <DocumentResults
                        results={msg.results.slice(0, 10)}
                        loading={false}
                        schema={schema}
                        fieldOverrides={null}
                      />
                    </div>
                  </details>
                  {msg.dsl_query && (
                    <details className="chat-agent-reasoning">
                      <summary>Generated DSL</summary>
                      <div className="chat-reasoning-content">
                        <div className="chat-reasoning-section">
                          <pre className="chat-reasoning-pre">{(() => { try { return JSON.stringify(JSON.parse(msg.dsl_query), null, 2); } catch(e) { return msg.dsl_query; } })()}</pre>
                        </div>
                      </div>
                    </details>
                  )}
                </>
              ) : msg.error ? (
                <div className="chat-error">{msg.error}</div>
              ) : (
                <div className="chat-summary">I couldn't find any results for that query. Try rephrasing your question.</div>
              )}
            </div>
          )}
        </div>
      ))}
      {loading && (
        <div className="chat-bubble chat-assistant">
          <div className="chat-typing">
            <span className="chat-typing-dot"></span>
            <span className="chat-typing-dot"></span>
            <span className="chat-typing-dot"></span>
          </div>
        </div>
      )}
      <div ref={endRef} />
    </div>
  );
}
