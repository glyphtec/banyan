import React from 'react'

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

function LinksSection({ title, links, nodeMap, crossGraphNodeMap, currentNodeId, graphMap, onSelect }) {
  if (!links || links.length === 0) return null
  return (
    <div className="detail-section">
      <h3>{title} <span style={{ fontWeight: 400, textTransform: 'none' }}>({links.length})</span></h3>
      <ul className="link-list">
        {links.map(l => {
          const peerId = l.from_node_id === currentNodeId ? l.to_node_id : l.from_node_id
          const peerGraphId = l.from_node_id === currentNodeId ? l.to_graph_id : l.from_graph_id
          const peer = nodeMap[peerId]
          const crossPeer = !peer ? crossGraphNodeMap?.[peerId] : null
          return (
            <li key={l.link_id}>
              <span className="link-badge">{l.link_type_name}</span>
              {peer
                ? <span className="link-name" onClick={() => onSelect(peer)}>{peer.name}</span>
                : crossPeer
                  ? (
                    <span className="link-name" style={{ fontStyle: 'italic' }} onClick={() => onSelect(crossPeer)}>
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
            </li>
          )
        })}
      </ul>
    </div>
  )
}

export function NodeDetail({ node, links, nodeMap, crossGraphNodeMap, graphMap, nodeTypeMap, hierarchicalIds, relatedIds, onSelect }) {
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

      <LinksSection title="Parents"  links={parentLinks}  nodeMap={nodeMap} crossGraphNodeMap={crossGraphNodeMap} graphMap={graphMap} currentNodeId={node.node_id} onSelect={onSelect} />
      <LinksSection title="Children" links={childLinks}   nodeMap={nodeMap} crossGraphNodeMap={crossGraphNodeMap} graphMap={graphMap} currentNodeId={node.node_id} onSelect={onSelect} />
      <LinksSection title="Related"  links={relatedLinks} nodeMap={nodeMap} crossGraphNodeMap={crossGraphNodeMap} graphMap={graphMap} currentNodeId={node.node_id} onSelect={onSelect} />
      {otherLinks.length > 0 && (
        <LinksSection title="Other" links={otherLinks} nodeMap={nodeMap} crossGraphNodeMap={crossGraphNodeMap} graphMap={graphMap} currentNodeId={node.node_id} onSelect={onSelect} />
      )}
    </div>
  )
}
