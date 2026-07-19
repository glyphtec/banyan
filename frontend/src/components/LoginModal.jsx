import React, { useState, useEffect } from 'react'
import { listActors, registerActor } from '../api'

function toHandle(displayName) {
  return 'human:' + displayName.toLowerCase().replace(/\s+/g, '.').replace(/[^a-z0-9.]/g, '')
}

export function LoginModal({ onLogin }) {
  const [actors, setActors]             = useState([])
  const [showRegister, setShowRegister] = useState(false)
  const [displayName, setDisplayName]   = useState('')
  const [handleSuffix, setHandleSuffix] = useState('')
  const [org, setOrg]                   = useState('')
  const [registering, setRegistering]   = useState(false)
  const [error, setError]               = useState(null)

  useEffect(() => {
    listActors()
      .then(all => {
        const humans = all.filter(a => a.actor_type === 'HUMAN')
        setActors(humans)
        if (humans.length === 0) setShowRegister(true)
      })
      .catch(() => setShowRegister(true))
  }, [])

  const derivedHandle = handleSuffix.trim()
    ? `human:${handleSuffix.trim()}`
    : displayName.trim() ? toHandle(displayName) : ''

  async function handleRegister(e) {
    e.preventDefault()
    setRegistering(true)
    setError(null)
    try {
      const actor = await registerActor({
        handle: derivedHandle,
        display_name: displayName.trim(),
        actor_type: 'HUMAN',
        org: org.trim() || undefined,
      })
      onLogin(actor.handle, actor.display_name)
    } catch (err) {
      setError(err.message)
      setRegistering(false)
    }
  }

  return (
    <div className="login-overlay">
      <div className="login-modal">
        <h1 className="login-title">Banyan</h1>
        <p className="login-subtitle">Identify yourself to begin</p>

        {actors.length > 0 && (
          <div className="login-section">
            <div className="login-section-label">Continue as</div>
            <div className="login-actor-list">
              {actors.map(a => (
                <button
                  key={a.handle}
                  className="login-actor-btn"
                  onClick={() => onLogin(a.handle, a.display_name)}
                >
                  <span className="login-actor-name">{a.display_name}</span>
                  <span className="login-actor-handle">{a.handle}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {actors.length > 0 && !showRegister && (
          <button className="login-register-toggle" onClick={() => setShowRegister(true)}>
            + Register new actor
          </button>
        )}

        {showRegister && (
          <form className="login-section login-register-form" onSubmit={handleRegister}>
            {actors.length > 0 && (
              <div className="login-section-label">Register new actor</div>
            )}
            <label>
              Display name
              <input
                type="text"
                value={displayName}
                onChange={e => setDisplayName(e.target.value)}
                placeholder="Jane Smith"
                required
                autoFocus
              />
            </label>
            <label>
              Handle <span className="login-optional">(auto-generated if blank)</span>
              <div className="login-handle-row">
                <span className="login-handle-prefix">human:</span>
                <input
                  type="text"
                  value={handleSuffix}
                  onChange={e => setHandleSuffix(e.target.value)}
                  placeholder={displayName.trim() ? toHandle(displayName).slice(6) : 'jane.smith'}
                />
              </div>
            </label>
            <label>
              Organisation <span className="login-optional">(optional)</span>
              <input
                type="text"
                value={org}
                onChange={e => setOrg(e.target.value)}
                placeholder="Acme Health"
              />
            </label>
            {error && <p className="login-error">{error}</p>}
            <button
              type="submit"
              className="login-submit-btn"
              disabled={!displayName.trim() || registering}
            >
              {registering ? 'Registering…' : 'Register & sign in'}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
