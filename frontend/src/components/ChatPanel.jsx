import React, { useState, useRef, useEffect, useCallback } from 'react'

const WELCOME = {
  role: 'assistant',
  content:
    "Hi — I'm the Banyan agent. I can explore the taxonomy graphs, look up nodes and links, " +
    "and help you create or remove crosswalk connections.\n\n" +
    "Select a node in the tree to give me context, then ask away. " +
    "Try: *\"What are the Gravity L1 social-risk domains?\"* or " +
    "*\"Show me the SNOMED codes for Food Insecurity.\"*",
  tool_calls: [],
}

function ToolCallPill({ tc }) {
  const [open, setOpen] = useState(false)
  const hasError = tc.result?.error
  return (
    <div className={`agent-tool-pill${hasError ? ' agent-tool-error' : ''}`}>
      <button className="agent-tool-summary" onClick={() => setOpen(o => !o)}>
        <span className="agent-tool-icon">{hasError ? '⚠' : '⚙'}</span>
        <span className="agent-tool-name">{tc.name}</span>
        <span className="agent-tool-chevron">{open ? '▴' : '▾'}</span>
      </button>
      {open && (
        <div className="agent-tool-detail">
          <div className="agent-tool-section">
            <span className="agent-tool-label">Input</span>
            <pre>{JSON.stringify(tc.input, null, 2)}</pre>
          </div>
          <div className="agent-tool-section">
            <span className="agent-tool-label">Result</span>
            <pre>{JSON.stringify(tc.result, null, 2)}</pre>
          </div>
        </div>
      )}
    </div>
  )
}

function Message({ msg }) {
  const isUser = msg.role === 'user'
  return (
    <div className={`agent-msg agent-msg-${msg.role}${msg.error ? ' agent-msg-err' : ''}`}>
      {!isUser && msg.tool_calls?.length > 0 && (
        <div className="agent-tools">
          {msg.tool_calls.map((tc, i) => <ToolCallPill key={i} tc={tc} />)}
        </div>
      )}
      <div className="agent-bubble">{msg.content}</div>
    </div>
  )
}

export function ChatPanel({ context, sessionId, style }) {
  const [messages, setMessages] = useState([WELCOME])
  const [input, setInput]       = useState('')
  const [loading, setLoading]   = useState(false)
  const bottomRef = useRef(null)
  const textareaRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const send = useCallback(async () => {
    const text = input.trim()
    if (!text || loading) return
    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: text, tool_calls: [] }])
    setLoading(true)
    try {
      const resp = await fetch('/api/v1/agent/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, message: text, context }),
      })
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }))
        throw new Error(err.detail || resp.statusText)
      }
      const data = await resp.json()
      setMessages(prev => [
        ...prev,
        { role: 'assistant', content: data.reply, tool_calls: data.tool_calls ?? [] },
      ])
    } catch (e) {
      setMessages(prev => [
        ...prev,
        { role: 'assistant', content: `Error: ${e.message}`, tool_calls: [], error: true },
      ])
    } finally {
      setLoading(false)
      textareaRef.current?.focus()
    }
  }, [input, loading, sessionId, context])

  const clearSession = useCallback(async () => {
    await fetch('/api/v1/agent/clear', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId }),
    }).catch(() => {})
    setMessages([WELCOME])
    setInput('')
  }, [sessionId])

  const onKeyDown = useCallback(e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
  }, [send])

  const contextLabel = context?.node_name
    ? `${context.node_name} · ${context.graph_name}`
    : context?.graph_name || 'No selection'

  return (
    <div className="agent-panel" style={style}>
      <div className="agent-header">
        <span className="agent-title">Agent</span>
        <span className="agent-context" title="Active context">{contextLabel}</span>
        <button className="agent-clear-btn" onClick={clearSession} title="Clear conversation">
          ↺
        </button>
      </div>

      <div className="agent-messages">
        {messages.map((msg, i) => <Message key={i} msg={msg} />)}
        {loading && (
          <div className="agent-msg agent-msg-assistant">
            <div className="agent-thinking">
              <span /><span /><span />
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="agent-input-area">
        <textarea
          ref={textareaRef}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask the agent… (Enter to send, Shift+Enter for newline)"
          rows={3}
          disabled={loading}
        />
        <button
          className="agent-send-btn"
          onClick={send}
          disabled={loading || !input.trim()}
        >
          Send
        </button>
      </div>
    </div>
  )
}
