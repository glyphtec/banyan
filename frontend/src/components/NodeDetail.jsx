import React, { useState } from 'react'

function fmtDt(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

function MetadataSection({ metadata }) {
  const entries = Object.entries(metadata ?? {}).filter(([, v]) => v !== null && v !== undefined)
  return (
    <div className="detail-section">
      <h3>Metadata</h3>
      {entries.length === 0
        ? <p className="detail-empty">—</p>
        : (
          <table className="kv-table">
            <tbody>
              {entries.map(([k, v]) => (
                <tr key={k}>
                  <td>{k}</td>
                  <td>{typeof v === 'object' ? JSON.stringify(v, null, 2) : String(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      }
    </div>
  )
}

function LinksSection({ title, links, nodeMap, crossGraphNodeMap, crossGraphParentMap, currentNodeId, graphMap, onSelect, showDirection, symmetricIds }) {
  const [expandedId, setExpandedId] = useState(null)
  if (!links || links.length === 0) return null

  function hasMeta(l) {
    const m = l.metadata ?? {}
    return m.agent_rationale || m.confidence_level || m.caveats
  }

  const CONF_COLORS = { HIGH: '#3a9e5f', MEDIUM: '#b07d20', LOW: '#b05030', UNCERTAIN: 'var(--text-dim)' }
  return (
    <div className="detail-section">
      <h3>{title} <span style={{ fontWeight: 400, textTransform: 'none' }}>({links.length})</span></h3>
      <ul className="link-list">
        {links.map(l => {
          const isOutbound = l.from_node_id === currentNodeId
          const peerId = isOutbound ? l.to_node_id : l.from_node_id
          const peerGraphId = isOutbound ? l.to_graph_id : l.from_graph_id
          const peer = nodeMap[peerId]
          const crossPeer = !peer ? crossGraphNodeMap?.[peerId] : null
          return (
            <li key={l.link_id}>
              <div className="link-row-main">
              <span className="link-badge">{l.link_type_name}</span>
              {showDirection && (
                <span style={{ color: 'var(--text-dim)', fontSize: '11px', marginRight: 4 }}>
                  {symmetricIds?.has(l.link_type_id) ? '<->' : isOutbound ? '→' : '←'}
                </span>
              )}
              {peer
                ? <span
                    className="link-name"
                    onClick={() => onSelect(peer)}
                    title={crossGraphParentMap?.[peerId] ? `${crossGraphParentMap[peerId]} \u203a ${peer.name}` : undefined}
                  >{peer.name}</span>
                : crossPeer
                  ? (
                    <span
                      className="link-name"
                      style={{ fontStyle: 'italic' }}
                      onClick={() => onSelect(crossPeer)}
                      title={crossGraphParentMap?.[peerId] ? `${crossGraphParentMap[peerId]} › ${crossPeer.name}` : undefined}
                    >
                      {crossPeer.name}
                      {graphMap?.[peerGraphId] && (
                        <span style={{ color: 'var(--text-dim)', fontSize: '11px', marginLeft: 4 }}>
                          [{graphMap[peerGraphId]}]
                        </span>
                      )}
                    </span>
                  )
                  : <span style={{ color: 'var(--text-dim)', fontStyle: 'italic' }}>{peerId}</span>
              }
              {hasMeta(l) && (
                <button
                  className="link-meta-toggle"
                  onClick={() => setExpandedId(expandedId === l.link_id ? null : l.link_id)}
                  title="Show evidence"
                >ⓘ</button>
              )}
              </div>
              {expandedId === l.link_id && (
                <div className="link-meta-panel">
                  {l.metadata?.confidence_level && (
                    <span
                      className="link-meta-conf-badge"
                      style={{ background: CONF_COLORS[l.metadata.confidence_level] ?? 'var(--text-dim)' }}
                    >
                      {l.metadata.confidence_level}
                    </span>
                  )}
                  {(l.metadata?.confidence_basis ?? []).map(b => (
                    <span key={b} className="link-meta-basis-tag">{b.replace(/_/g, ' ')}</span>
                  ))}
                  {l.metadata?.agent_rationale && (
                    <p className="link-meta-rationale">"{l.metadata.agent_rationale}"</p>
                  )}
                  {l.metadata?.caveats && (
                    <p className="link-meta-caveats">⚠ {l.metadata.caveats}</p>
                  )}
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

export function NodeDetail({ node, links, nodeMap, crossGraphNodeMap, crossGraphParentMap, graphMap, nodeTypeMap, hierarchicalIds, relatedIds, symmetricIds, onSelect }) {
  if (!node) {
    return (
      <div className="detail-panel">
        <p className="empty">Select a node to inspect it.</p>
      </div>
    )
  }

  function labeled(map, id) {
    const name = map?.[id]
    return name ? <>{name} <span style={{ color: 'var(--text-dim)', fontFamily: 'var(--mono)', fontSize: '11px' }}>({id})</span></> : id
  }

  const hierarchical = new Set(hierarchicalIds)
  const related      = new Set(relatedIds)

  const parentLinks  = links.filter(l => l.to_node_id   === node.node_id && hierarchical.has(l.link_type_id))
  const childLinks   = links.filter(l => l.from_node_id === node.node_id && hierarchical.has(l.link_type_id))
  const relatedLinks = links.filter(l =>
    (l.from_node_id === node.node_id || l.to_node_id === node.node_id) && related.has(l.link_type_id)
  )
  const otherLinks   = links.filter(l =>
    (l.from_node_id === node.node_id || l.to_node_id === node.node_id) &&
    !hierarchical.has(l.link_type_id) && !related.has(l.link_type_id)
  )

  return (
    <div className="detail-panel">
      <h2>{node.name}</h2>
      <div className="source-id">{node.source_id}</div>

      <div className="detail-section">
        <h3>Notes</h3>
        {node.notes
          ? <p>{node.notes}</p>
          : <p className="detail-empty">—</p>
        }
      </div>

      <div className="detail-section">
        <h3>Identity</h3>
        <table className="kv-table">
          <tbody>
            <tr><td>node_id</td><td>{node.node_id}</td></tr>
            <tr><td>graph_id</td><td>{labeled(graphMap, node.graph_id)}</td></tr>
            <tr><td>node_type</td><td>{labeled(nodeTypeMap, node.node_type_id)}</td></tr>
          </tbody>
        </table>
      </div>

      <MetadataSection metadata={node.metadata} />

      <div className="detail-section">
        <h3>Audit</h3>
        <table className="kv-table">
          <tbody>
            <tr><td>inserted</td><td>{fmtDt(node.inserted_datetime)}</td></tr>
            <tr><td>updated</td><td>{fmtDt(node.updated_datetime)}</td></tr>
            <tr><td>updated_by</td><td>{node.updated_by ?? '—'}</td></tr>
          </tbody>
        </table>
      </div>

      <LinksSection title="Parents"  links={parentLinks}  nodeMap={nodeMap} crossGraphNodeMap={crossGraphNodeMap} crossGraphParentMap={crossGraphParentMap} graphMap={graphMap} currentNodeId={node.node_id} onSelect={onSelect} />
      <LinksSection title="Children" links={childLinks}   nodeMap={nodeMap} crossGraphNodeMap={crossGraphNodeMap} crossGraphParentMap={crossGraphParentMap} graphMap={graphMap} currentNodeId={node.node_id} onSelect={onSelect} />
      <LinksSection title="Related"  links={relatedLinks} nodeMap={nodeMap} crossGraphNodeMap={crossGraphNodeMap} crossGraphParentMap={crossGraphParentMap} graphMap={graphMap} currentNodeId={node.node_id} onSelect={onSelect} showDirection symmetricIds={symmetricIds} />
      {otherLinks.length > 0 && (
        <LinksSection title="Other" links={otherLinks} nodeMap={nodeMap} crossGraphNodeMap={crossGraphNodeMap} crossGraphParentMap={crossGraphParentMap} graphMap={graphMap} currentNodeId={node.node_id} onSelect={onSelect} showDirection symmetricIds={symmetricIds} />
      )}
    </div>
  )
}
