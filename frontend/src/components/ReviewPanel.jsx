import React, { useState, useEffect, useCallback } from 'react'
import { bqlQuery, exportGraph, executeBatch, updateLink } from '../api'

// Strip _PROPOSED suffix to get the convention-derived confirmed type name.
function deriveConfirmedName(proposedName) {
  return proposedName.replace(/_PROPOSED$/, '')
}

// Walk the childToParent map to build a breadcrumb string for a target node.
function buildPath(nodeId, nodeName, childToParent, ancestorNames) {
  const path = [nodeName]
  let cur = nodeId
  let guard = 8
  while (childToParent[cur] && guard-- > 0) {
    const pid = childToParent[cur]
    const pname = ancestorNames[pid]
    if (!pname || pname === '$ROOT$') break
    path.unshift(pname)
    cur = pid
  }
  return path.join(' \u203a ')
}

export function ReviewPanel({ graphs, relatedTypes, graphMap, actorHandle, onNavigate, onReveal, onMutated }) {
  const visibleGraphs  = graphs.filter(g => g.name !== '__system__')
  const proposedTypes  = relatedTypes.filter(lt => lt.name.endsWith('_PROPOSED'))
  const confirmedTypes = relatedTypes.filter(lt => !lt.name.endsWith('_PROPOSED'))

  // ── Toolbar state ──────────────────────────────────────────────────────────
  const [reviewGraphId, setReviewGraphId] = useState('')
  const [filterTypeId,  setFilterTypeId]  = useState('')
  const [approveTypeId, setApproveTypeId] = useState('')
  const [deleteProposed, setDeleteProposed] = useState(true)

  // Initialise graph selection once graphs arrive
  useEffect(() => {
    if (!reviewGraphId && visibleGraphs.length > 0)
      setReviewGraphId(visibleGraphs[0].graph_id)
  }, [visibleGraphs.length])   // eslint-disable-line react-hooks/exhaustive-deps

  // Initialise filter type once relatedTypes arrive
  useEffect(() => {
    if (!filterTypeId && proposedTypes.length > 0)
      setFilterTypeId(proposedTypes[0].link_type_id)
  }, [proposedTypes.length])   // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-derive approve-as from the convention when filter changes
  useEffect(() => {
    if (!filterTypeId) return
    const ft = proposedTypes.find(lt => lt.link_type_id === filterTypeId)
    if (!ft) return
    const ct = confirmedTypes.find(lt => lt.name === deriveConfirmedName(ft.name))
    if (ct) setApproveTypeId(ct.link_type_id)
  }, [filterTypeId])   // eslint-disable-line react-hooks/exhaustive-deps

  // ── Queue data ─────────────────────────────────────────────────────────────
  const [queueItems, setQueueItems] = useState([])
  const [loading, setLoading]       = useState(false)
  const [fetchError, setFetchError] = useState(null)

  const fetchQueue = useCallback(async () => {
    if (!reviewGraphId || !filterTypeId) return
    const ft = relatedTypes.find(lt => lt.link_type_id === filterTypeId)
    if (!ft) return

    setLoading(true)
    setFetchError(null)
    try {
      // Use exportGraph instead of BQL — works for flat AND hierarchical graphs.
      // exportGraph returns cross_graph_links (bidirectional) regardless of structure.
      const exp = await exportGraph(reviewGraphId)
      const allLinks = [...(exp.links ?? []), ...(exp.cross_graph_links ?? [])]
      const proposed = allLinks.filter(l => l.link_type_name === ft.name)

      if (proposed.length === 0) { setQueueItems([]); return }

      // from-node map: all nodes in the review graph
      const fromNodeMap = Object.fromEntries(exp.nodes.map(n => [n.node_id, n]))

      // Collect peer node IDs grouped by their graph, for BQL ancestor lookup
      const peersByGraph = {}   // graph_id → Set<node_id>
      for (const l of proposed) {
        const peerGraphId = l.from_graph_id === reviewGraphId ? l.to_graph_id : l.from_graph_id
        const peerNodeId  = l.from_graph_id === reviewGraphId ? l.to_node_id  : l.from_node_id
        if (!peersByGraph[peerGraphId]) peersByGraph[peerGraphId] = new Set()
        peersByGraph[peerGraphId].add(peerNodeId)
      }

      const childToParent = {}
      const ancestorNames = {}
      const peerNodeMap   = {}

      // One BQL query per peer graph: fetch seed nodes + their ancestors
      for (const [peerGraphId, nodeIdSet] of Object.entries(peersByGraph)) {
        const nodeIds = [...nodeIdSet]
        const startingPred = nodeIds.length === 1
          ? { node_id: nodeIds[0] }
          : { or: nodeIds.map(id => ({ node_id: id })) }
        const result = await bqlQuery({
          graph:    { id: peerGraphId },
          starting: startingPred,
          steps: [{ direction: 'TO', link_types: ['HIERARCHICAL'], depth: 10, collect: true }],
          result:   { format: 'LINK_NODE', include_seed: true },
        })
        for (const item of result.results) {
          if (item._step === 0 && item.node)
            peerNodeMap[item.node.node_id] = item.node
          else if (item._step === 1 && item.link && item.node) {
            const childId = item.link.to_node_id
            if (!childToParent[childId]) childToParent[childId] = item.node.node_id
            ancestorNames[item.node.node_id] = item.node.name
          }
        }
      }

      const enriched = proposed.map(l => {
        const fromInReview = l.from_graph_id === reviewGraphId
        const fromNode = fromInReview
          ? (fromNodeMap[l.from_node_id] ?? { node_id: l.from_node_id, name: l.from_source_id ?? '(unknown)', graph_id: reviewGraphId })
          : (peerNodeMap[l.from_node_id] ?? { node_id: l.from_node_id, name: l.from_source_id ?? '(unknown)', graph_id: l.from_graph_id })
        const toNode = fromInReview
          ? (peerNodeMap[l.to_node_id] ?? { node_id: l.to_node_id, name: l.to_source_id ?? '(unknown)', graph_id: l.to_graph_id })
          : (fromNodeMap[l.to_node_id] ?? { node_id: l.to_node_id, name: l.to_source_id ?? '(unknown)', graph_id: reviewGraphId })
        return {
          link:        l,
          fromNode,
          toNode,
          toPath:      buildPath(toNode.node_id, toNode.name, childToParent, ancestorNames),
          toGraphName: graphMap[toNode.graph_id] ?? toNode.graph_id,
        }
      })

      setQueueItems(enriched)
    } catch (e) {
      setFetchError(e.message)
    } finally {
      setLoading(false)
    }
  }, [reviewGraphId, filterTypeId, relatedTypes, graphMap])

  useEffect(() => { fetchQueue() }, [fetchQueue])

  // ── Row action state ───────────────────────────────────────────────────────
  const [processingIds, setProcessingIds] = useState(new Set())
  const [rowErrors,     setRowErrors]     = useState({})   // link_id → msg
  const [passingId,     setPassingId]     = useState(null) // link_id with open pass form
  const [passNote,      setPassNote]      = useState('')

  const markProcessing = (id, on) =>
    setProcessingIds(prev => { const s = new Set(prev); on ? s.add(id) : s.delete(id); return s })

  const handleApprove = useCallback(async (item) => {
    if (!approveTypeId) return
    const { link, fromNode, toNode } = item
    markProcessing(link.link_id, true)
    setRowErrors(prev => { const n = { ...prev }; delete n[link.link_id]; return n })
    try {
      const linkOps = []
      if (deleteProposed)
        linkOps.push({ verb: 'DESTROY_LINK', data: { link_id: link.link_id } })
      linkOps.push({
        verb: 'CREATE_LINK',
        data: {
          from_node_id: fromNode.node_id,
          to_node_id:   toNode.node_id,
          to_graph_id:  toNode.graph_id,
          link_type_id: approveTypeId,
          metadata: {
            link_provenance: 'asserted',
            approved_by:     actorHandle,
            ...(link.metadata?.agent_rationale    ? { agent_rationale:    link.metadata.agent_rationale }    : {}),
            ...(link.metadata?.confidence_level   ? { confidence_level:   link.metadata.confidence_level }   : {}),
            ...(link.metadata?.confidence_basis   ? { confidence_basis:   link.metadata.confidence_basis }   : {}),
            ...(link.metadata?.caveats            ? { caveats:            link.metadata.caveats }            : {}),
          },
          // from_graph_id may differ from reviewGraphId for cross-graph links
          // (e.g. reviewing OE but the from-node lives in SNOMED SR).
          from_graph_id: fromNode.graph_id,
        },
      })
      await executeBatch(
        { graph_id: reviewGraphId, actor_id: actorHandle, link_operations: linkOps },
        actorHandle,
      )
      setQueueItems(prev => prev.filter(i => i.link.link_id !== link.link_id))
      onMutated?.()
    } catch (e) {
      setRowErrors(prev => ({ ...prev, [link.link_id]: e.message }))
    } finally {
      markProcessing(link.link_id, false)
    }
  }, [approveTypeId, deleteProposed, reviewGraphId, actorHandle])

  const handlePass = useCallback(async (item) => {
    const { link } = item
    markProcessing(link.link_id, true)
    try {
      const newMeta = {
        ...link.metadata,
        reviewer_note:  passNote.trim() || undefined,
        review_status:  'deferred',
        reviewed_by:    actorHandle,
      }
      await updateLink(link.link_id, { metadata: newMeta }, actorHandle)
      setQueueItems(prev => prev.map(i =>
        i.link.link_id === link.link_id
          ? { ...i, link: { ...i.link, metadata: newMeta } }
          : i,
      ))
      setPassingId(null)
      setPassNote('')
      onMutated?.()
    } catch (e) {
      setRowErrors(prev => ({ ...prev, [link.link_id]: e.message }))
    } finally {
      markProcessing(link.link_id, false)
    }
  }, [passNote, actorHandle])

  const filterType  = relatedTypes.find(lt => lt.link_type_id === filterTypeId)
  const approveType = relatedTypes.find(lt => lt.link_type_id === approveTypeId)

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="review-panel">

      {/* ── Toolbar ─────────────────────────────────────────────────────── */}
      <div className="review-toolbar">
        <div className="review-toolbar-row">
          <span className="review-label">Graph</span>
          <select value={reviewGraphId} onChange={e => setReviewGraphId(e.target.value)}>
            {visibleGraphs.map(g => (
              <option key={g.graph_id} value={g.graph_id}>{g.name}</option>
            ))}
          </select>
        </div>
        <div className="review-toolbar-row">
          <span className="review-label">Show</span>
          <select value={filterTypeId} onChange={e => setFilterTypeId(e.target.value)}>
            {proposedTypes.map(lt => (
              <option key={lt.link_type_id} value={lt.link_type_id}>{lt.name}</option>
            ))}
          </select>
        </div>
        <div className="review-toolbar-row">
          <span className="review-label">Approve as</span>
          <select value={approveTypeId} onChange={e => setApproveTypeId(e.target.value)}>
            {confirmedTypes.map(lt => (
              <option key={lt.link_type_id} value={lt.link_type_id}>{lt.name}</option>
            ))}
          </select>
          <label className="review-checkbox-label">
            <input
              type="checkbox"
              checked={deleteProposed}
              onChange={e => setDeleteProposed(e.target.checked)}
            />
            del proposed
          </label>
          <button className="review-refresh-btn" onClick={fetchQueue} title="Refresh queue">↺</button>
        </div>
      </div>

      {/* ── Count bar ───────────────────────────────────────────────────── */}
      <div className="review-count">
        {loading
          ? 'Loading…'
          : fetchError
            ? <span style={{ color: '#e05c5c' }}>{fetchError}</span>
            : `${queueItems.length} pending`
        }
      </div>

      {/* ── Queue ───────────────────────────────────────────────────────── */}
      <div className="review-queue">
        {!loading && !fetchError && queueItems.length === 0 && (
          <div className="review-empty">
            No pending {filterType?.name ?? ''} links
          </div>
        )}

        {queueItems.map(item => {
          const { link, fromNode, toNode, toPath, toGraphName } = item
          const isProcessing = processingIds.has(link.link_id)
          const rowError     = rowErrors[link.link_id]
          const isPassing    = passingId === link.link_id
          const isDeferred   = link.metadata?.review_status === 'deferred'

          return (
            <div key={link.link_id} className={`review-row${isDeferred ? ' review-row-deferred' : ''}`}>

              {/* From → To */}
              <div className="review-row-nodes">
                <span
                  className="review-node"
                  onClick={() => { onNavigate(fromNode); onReveal?.(fromNode) }}
                  title={fromNode.source_id}
                >
                  {fromNode.name}
                </span>
                <span className="review-arrow">→</span>
                <span>
                  <span
                    className="review-node"
                    onClick={() => { onNavigate(toNode); onReveal?.(toNode) }}
                    title={toNode.source_id}
                  >
                    {toNode.name}
                  </span>
                  <span className="review-graph-badge">[{toGraphName}]</span>
                </span>
              </div>

              {/* Breadcrumb path (only if it adds context beyond the node name) */}
              {toPath !== toNode.name && (
                <div className="review-breadcrumb">{toPath}</div>
              )}

              {/* Confidence badge + basis tags */}
              {link.metadata?.confidence_level && (
                <div className="review-confidence-row">
                  <span className={`review-confidence-badge review-conf-${link.metadata.confidence_level.toLowerCase()}`}>
                    {link.metadata.confidence_level}
                  </span>
                  {(link.metadata.confidence_basis ?? []).map(b => (
                    <span key={b} className="review-basis-tag">{b.replace(/_/g, ' ')}</span>
                  ))}
                </div>
              )}

              {/* Agent rationale */}
              {link.metadata?.agent_rationale && (
                <div className="review-rationale">
                  "{link.metadata.agent_rationale}"
                </div>
              )}

              {/* Deferred status */}
              {isDeferred && (
                <div className="review-deferred-row">
                  <span className="review-deferred-badge">deferred</span>
                  {link.metadata?.reviewer_note && (
                    <span className="review-rationale" style={{ marginLeft: 6 }}>
                      {link.metadata.reviewer_note}
                    </span>
                  )}
                </div>
              )}

              {/* Row error */}
              {rowError && (
                <div style={{ fontSize: 11, color: '#e05c5c' }}>{rowError}</div>
              )}

              {/* Action buttons */}
              {!isPassing && (
                <div className="review-row-actions">
                  <button
                    className="review-approve-btn"
                    disabled={isProcessing || !approveTypeId}
                    onClick={() => handleApprove(item)}
                  >
                    {isProcessing ? '…' : `✓ ${approveType?.name ?? 'Approve'}`}
                  </button>
                  <button
                    className="review-pass-btn"
                    disabled={isProcessing}
                    onClick={() => { setPassingId(link.link_id); setPassNote('') }}
                  >
                    ⊘ Pass
                  </button>
                </div>
              )}

              {/* Pass / defer form */}
              {isPassing && (
                <div className="review-pass-form">
                  <input
                    autoFocus
                    type="text"
                    placeholder="Note (optional) — Enter to save, Esc to cancel"
                    value={passNote}
                    onChange={e => setPassNote(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter')  handlePass(item)
                      if (e.key === 'Escape') { setPassingId(null); setPassNote('') }
                    }}
                  />
                  <button className="review-approve-btn" onClick={() => handlePass(item)}>
                    Save
                  </button>
                  <button
                    className="review-pass-btn"
                    onClick={() => { setPassingId(null); setPassNote('') }}
                  >
                    Cancel
                  </button>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
