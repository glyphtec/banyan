import React, { useState, useEffect, useCallback } from 'react'
import { bqlQuery, executeBatch, updateLink } from '../api'

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
      const data = await bqlQuery({
        graph: { id: reviewGraphId },
        steps: [
          // Step 1: fan out to all nodes in the review graph (no collect).
          { direction: 'FROM', link_types: ['HIERARCHICAL'], depth: 50, collect: false },
          // Step 2: WITH so both directions of each symmetric link are collected,
          // giving us both endpoint node objects without a separate lookup.
          { direction: 'WITH', link_types: [ft.name + '!'], depth: 1, graphs: ['*'], collect: true },
          // Step 3: ancestors of step-2 peer nodes for breadcrumb context.
          { direction: 'TO', link_types: ['HIERARCHICAL'], depth: 10, graphs: ['*'], collect: true },
        ],
        result: { format: 'LINK_NODE', include_seed: false },
      })

      // Step 1 has collect:false — builds frontier only, no results.
      // Step 2 WITH traversal: with per-step seen, both endpoint nodes of each
      //   symmetric link are collected (one item per direction per link).
      //   Group by link_id so we have both nodes for free — no extra lookup.
      // Step 3 TO HIERARCHICAL: ancestors of step-2 peers for breadcrumbs.

      const byLinkId  = {}   // link_id → { fromItem, toItem }
      const childToParent = {}
      const ancestorNames = {}

      for (const item of data.results) {
        if (item._step === 2 && item.link && item.node) {
          const lid = item.link.link_id
          if (!byLinkId[lid]) byLinkId[lid] = {}
          // FROM direction: we arrived at the to_node
          // TO direction:   we arrived at the from_node
          if (item._direction === 'FROM') byLinkId[lid].toItem  = item
          else                            byLinkId[lid].fromItem = item
        } else if (item._step === 3 && item.link && item.node) {
          const childId = item.link.to_node_id
          if (!childToParent[childId]) childToParent[childId] = item.node.node_id
          ancestorNames[item.node.node_id] = item.node.name
        }
      }

      const enriched = Object.values(byLinkId)
        .filter(({ fromItem, toItem }) => fromItem && toItem)
        .map(({ fromItem, toItem }) => {
          const fromNode = fromItem.node   // node we arrived at via TO direction = from_node
          const toNode   = toItem.node    // node we arrived at via FROM direction = to_node
          const link     = toItem.link    // same link either way
          return {
            link,
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
            ...(link.metadata?.agent_rationale
              ? { agent_rationale: link.metadata.agent_rationale }
              : {}),
          },
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
