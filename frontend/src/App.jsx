import React, { useState, useRef, useEffect } from 'react';
import ChatMessage from './components/ChatMessage';
import './App.css';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

function generateSessionId() {
  return 's-' + Math.random().toString(36).substring(2, 10);
}

function App() {
  const [sessionId] = useState(() => generateSessionId());
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [showSystemPrompt, setShowSystemPrompt] = useState(false);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const sendMessage = async () => {
    const trimmed = input.trim();
    if (!trimmed || isLoading) return;

    // Add user message to UI
    const userMessage = { role: 'user', content: trimmed };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    try {
      const body = {
        session_id: sessionId,
        message: trimmed,
      };
      if (systemPrompt.trim()) {
        body.system_prompt = systemPrompt.trim();
      }

      const response = await fetch(`${API_URL}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
        const errorMessage = {
          role: 'error',
          content: `Error ${response.status}: ${errorData.detail || 'Something went wrong'}`,
        };
        setMessages(prev => [...prev, errorMessage]);
        return;
      }

      const data = await response.json();
      const assistantMessage = {
        role: 'assistant',
        content: data.reply,
        metadata: data.metadata,
      };
      setMessages(prev => [...prev, assistantMessage]);
    } catch (error) {
      const errorMessage = {
        role: 'error',
        content: `Network error: ${error.message}`,
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
      inputRef.current?.focus();
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="app">
      <header className="app-header">
        <h1>🤖 LLM Chatbot</h1>
        <div className="header-info">
          <span className="session-badge">Session: {sessionId}</span>
          <button
            className="toggle-system-prompt"
            onClick={() => setShowSystemPrompt(!showSystemPrompt)}
          >
            {showSystemPrompt ? 'Hide' : 'Show'} System Prompt
          </button>
        </div>
      </header>

      {showSystemPrompt && (
        <div className="system-prompt-container">
          <textarea
            data-testid="system-prompt-input"
            className="system-prompt-input"
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
            placeholder="Enter a custom system prompt for this session..."
            rows={2}
          />
        </div>
      )}

      <div className="messages-container">
        {messages.length === 0 && (
          <div className="empty-state">
            <p>👋 Start a conversation! Type a message below.</p>
          </div>
        )}
        {messages.map((msg, index) => (
          <ChatMessage key={index} message={msg} />
        ))}
        {isLoading && (
          <div className="loading-indicator">
            <div className="typing-dots">
              <span></span><span></span><span></span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="input-container">
        <textarea
          data-testid="chat-input"
          ref={inputRef}
          className="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type your message..."
          rows={1}
          disabled={isLoading}
        />
        <button
          data-testid="send-button"
          className="send-button"
          onClick={sendMessage}
          disabled={isLoading || !input.trim()}
        >
          {isLoading ? '⏳' : '➤'}
        </button>
      </div>
    </div>
  );
}

export default App;
