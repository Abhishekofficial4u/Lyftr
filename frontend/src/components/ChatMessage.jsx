import React from 'react';
import './ChatMessage.css';

function ChatMessage({ message }) {
  if (message.role === 'error') {
    return (
      <div className="message error-message">
        <div className="message-content error-content">
          ⚠️ {message.content}
        </div>
      </div>
    );
  }

  if (message.role === 'user') {
    return (
      <div className="message user-message">
        <div className="message-content user-content">
          {message.content}
        </div>
      </div>
    );
  }

  // Assistant message
  const meta = message.metadata || {};

  return (
    <div className="message assistant-message" data-testid="assistant-message">
      <div className="message-content assistant-content">
        <div className="reply-text">{message.content}</div>
        <div className="metadata-bar">
          <span className={`meta-badge ${meta.resolution_source === 'LLM_CACHE' ? 'cache' : 'live'}`} data-testid="meta-source">
            {meta.resolution_source}
          </span>
          <span className="meta-item" data-testid="meta-model">
            🧠 {meta.model}
          </span>
          <span className="meta-item" data-testid="meta-latency">
            ⏱️ {meta.latency_ms} ms
          </span>
          <span className="meta-item" data-testid="meta-input-tokens">
            📥 {meta.input_tokens}
          </span>
          <span className="meta-item" data-testid="meta-output-tokens">
            📤 {meta.output_tokens}
          </span>
        </div>
      </div>
    </div>
  );
}

export default ChatMessage;
