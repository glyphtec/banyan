import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import './App.css'
import { listGraphs, exportGraph, getLinkTypes, getNodeTypes, bqlQuery } from './api'
import { buildHierarchicalFamily, buildTree } from './treeUtils'
import { GraphPicker } from './components/GraphPicker'
import { NodeTree } from './components/NodeTree'
import { NodeDetail } from './components/NodeDetail'
import { ChatPanel } from './components/ChatPanel'
import { LoginModal } from './components/LoginModal'
import { ReviewPanel } from './components/ReviewPanel'

export function App() {
  const [graphs, setGraphs]           = useState([])
  const [selectedGraphId, setSelected] = useState(null)
  const [exportData, setExportData]   = useState(null)   // { nodes, links, graph }
  const [linkTypes, setLinkTypes]     = useState([])  // HIERARCHICAL family
  const [relatedTypes, setRelatedTypes] = useState([]) // RELATED family
  const [nodeTypes, setNodeTypes]     = useState([])
  const [searchTerm, setSearchTerm]   = useState('')
  const [activeNode, setActiveNode]   = useState(null)
  const [status, setStatus]           = useState({ text: '', error: false })
  const [loadingGraph, setLoadingGraph] = useState(false)
  const [crossGraphNodeMap, setCrossGraphNodeMap] = useState({})
  const [crossGraphParentMap, setCrossGraphParentMap] = useState({})
  const [navHistory, setNavHistory]               = useState([])  // [{node_id, graph_id}]
  const [rightPanelOpen, setRightPanelOpen]         = useState(false)
  const [rightPanelTab,  setRightPanelTab]          = useState('agent')  // 'agent' | 'review'
  const [rightPanelWidth, setRightPanelWidth]       = useState(420)
  const [sidebarWidth, setSidebarWidth] = useState(320)
  const nodeTreeRef          = useRef(null)
  const dragging             = useRef(false)
  const draggingRightPanel   = useRef(false)
  const pendingNodeIdRef    = useRef(null)
  const pendingRevealIdRef  = useRef(null)
  // Stable session ID for the agent (survives re-renders, reset on page reload)
  const sessionId = useRef(Math.random().toString(36).slice(2)).current

  // Actor identity — persisted in sessionStorage so it survives page refreshes
  // within the same tab but clears when the tab closes.
  const [actorHandle, setActorHandle]           = useState(() => sessionStorage.getItem('banyan_actor_handle') || null)
  const [actorDisplayName, setActorDisplayName] = useState(() => sessionStorage.getItem('banyan_actor_display_name') || null)

  const handleLogin = useCallback((handle, displayName) => {
    sessionStorage.setItem('banyan_actor_handle', handle)
    sessionStorage.setItem('banyan_actor_display_name', displayName)
    setActorHandle(handle)
    setActorDisplayName(displayName)
  }, [])

  const handleSwitchActor = useCallback(() => {
    sessionStorage.removeItem('banyan_actor_handle')
    sessionStorage.removeItem('banyan_actor_display_name')
    setActorHandle(null)
    setActorDisplayName(null)
  }, [])

  const onSplitterMouseDown = useCallback(e => {
    e.preventDefault()
    dragging.current = true
    const onMove = ev => {
      if (!dragging.current) return
      setSidebarWidth(Math.min(Math.max(ev.clientX, 160), window.innerWidth * 0.75))
    }
    const onUp = () => {
      dragging.current = false
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [])

  const onRightSplitterMouseDown = useCallback(e => {
    e.preventDefault()
    draggingRightPanel.current = true
    const onMove = ev => {
      if (!draggingRightPanel.current) return
      const right = window.innerWidth - ev.clientX
      setRightPanelWidth(Math.min(Math.max(right, 280), window.innerWidth * 0.65))
    }
    const onUp = () => {
      draggingRightPanel.current = false
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [])

  // Boot: fetch graph list + link types in parallel
  useEffect(() => {
    setStatus({ text: 'Loading…', error: false })
    Promise.all([listGraphs(), getLinkTypes('HIERARCHICAL'), getLinkTypes('RELATED'), getNodeTypes()])
      .then(([gs, lts, rlts, nts]) => {
        const visible = gs.filter(g => g.name !== '__system__')
        setGraphs(visible)
        setLinkTypes(lts)
        setRelatedTypes(rlts)
        setNodeTypes(nts)
        setStatus({ text: `${visible.length} graph${visible.length !== 1 ? 's' : ''}`, error: false })
      })
      .catch(err => setStatus({ text: err.message, error: true }))
  }, [])

  // Load graph when selection changes
  useEffect(() => {
    if (!selectedGraphId) return
    setLoadingGraph(true)
    setExportData(null)
    setActiveNode(null)
    setStatus({ text: 'Loading graph…', error: false })
    exportGraph(selectedGraphId)
      .then(data => {
        setExportData(data)
        const crossCount = data.cross_graph_links?.length ?? 0
        setStatus({
          text: `${data.nodes.length} nodes · ${data.links.length} links${crossCount ? ` · ${crossCount} cross-graph` : ''}`,
          error: false,
        })
        // Resolve any pending cross-graph navigation
        if (pendingNodeIdRef.current) {
          const pending = data.nodes.find(n => n.node_id === pendingNodeIdRef.current)
          if (pending) {
            setActiveNode(pending)
            // revealNode is driven by the activeNode useEffect below
          }
          pendingNodeIdRef.current = null
        }
      })
      .catch(err => setStatus({ text: err.message, error: true }))
      .finally(() => setLoadingGraph(false))
  }, [selectedGraphId])

  const hierarchicalIds = useMemo(() => buildHierarchicalFamily(linkTypes), [linkTypes])
  const relatedIds   = useMemo(() => new Set(relatedTypes.map(lt => lt.link_type_id)), [relatedTypes])
  const symmetricIds = useMemo(() => new Set(relatedTypes.filter(lt => lt.is_symmetric).map(lt => lt.link_type_id)), [relatedTypes])

  const { tree: treeData, orphanCount } = useMemo(() => {
    if (!exportData) return { tree: [], orphanCount: 0 }
    return buildTree(exportData.nodes, exportData.links, hierarchicalIds)
  }, [exportData, hierarchicalIds])

  const nodeMap = useMemo(() => {
    if (!exportData) return {}
    return Object.fromEntries(exportData.nodes.map(n => [n.node_id, n]))
  }, [exportData])

  const graphMap = useMemo(
    () => Object.fromEntries(graphs.map(g => [g.graph_id, g.name])),
    [graphs]
  )

  const nodeTypeMap = useMemo(
    () => Object.fromEntries(nodeTypes.map(t => [t.node_type_id, t.name])),
    [nodeTypes]
  )

  // Reveal the active node in the tree whenever programmatic navigation sets it.
  // pendingRevealIdRef is set by navigateToNode / navigateBack before calling setActiveNode.
  useEffect(() => {
    if (!activeNode || pendingRevealIdRef.current !== activeNode.node_id) return
    pendingRevealIdRef.current = null
    nodeTreeRef.current?.revealNode(activeNode.node_id)
  }, [activeNode])

  // Navigate to a node, pushing the current position onto the back stack.
  // Handles both same-graph (instant) and cross-graph (triggers graph switch + pending resolve).
  const navigateToNode = useCallback((node) => {
    // No-op if already on this node — prevents spurious re-entry from TreeApi.select()
    // triggering the onSelect callback after a programmatic reveal.
    if (activeNode?.node_id === node.node_id && selectedGraphId === node.graph_id) return
    if (activeNode) {
      setNavHistory(prev => [...prev, { node_id: activeNode.node_id, graph_id: selectedGraphId }])
    }
    if (node.graph_id === selectedGraphId) {
      pendingRevealIdRef.current = node.node_id
      setActiveNode(node)
    } else {
      pendingRevealIdRef.current = node.node_id
      pendingNodeIdRef.current = node.node_id
      setSearchTerm('')
      setSelected(node.graph_id)
    }
  }, [activeNode, selectedGraphId])

  // Pop the back stack and navigate to the previous position.
  const navigateBack = useCallback(() => {
    if (navHistory.length === 0) return
    const prev = navHistory[navHistory.length - 1]
    setNavHistory(h => h.slice(0, -1))
    if (prev.graph_id === selectedGraphId) {
      const node = nodeMap[prev.node_id] ?? null
      if (node) pendingRevealIdRef.current = node.node_id
      setActiveNode(node)
    } else {
      pendingRevealIdRef.current = prev.node_id
      pendingNodeIdRef.current = prev.node_id
      setSearchTerm('')
      setSelected(prev.graph_id)
    }
  }, [navHistory, selectedGraphId, nodeMap])

  // Dispatch UI actions emitted by the agent.
  const handleAgentAction = useCallback((action) => {
    if (action.type === 'navigate_node') {
      if (action.graph_id === selectedGraphId) {
        const node = nodeMap[action.node_id]
        if (node) navigateToNode(node)
      } else {
        // Cross-graph: minimal stub; navigateToNode handles graph switch + pending resolve
        navigateToNode({ node_id: action.node_id, graph_id: action.graph_id })
      }
    } else if (action.type === 'select_graph') {
      setSelected(action.graph_id)
      setSearchTerm('')
      setNavHistory([])
    }
  }, [selectedGraphId, nodeMap, navigateToNode])

  // Direct tree reveal without going through navigateToNode.
  // Used by ReviewPanel so clicking an already-active node still scrolls the tree
  // without triggering the onSelect → navigateToNode → revealNode feedback loop.
  const revealInTree = useCallback((node) => {
    if (node.graph_id === selectedGraphId) {
      nodeTreeRef.current?.revealNode(node.node_id)
    }
  }, [selectedGraphId])

  // Re-fetch the currently loaded graph export after a mutation (e.g. link approve/pass).
  const refreshGraph = useCallback(() => {
    if (!selectedGraphId) return
    exportGraph(selectedGraphId)
      .then(data => {
        setExportData(data)
        const crossCount = data.cross_graph_links?.length ?? 0
        setStatus({
          text: `${data.nodes.length} nodes \u00b7 ${data.links.length} links${crossCount ? ` \u00b7 ${crossCount} cross-graph` : ''}`,
          error: false,
        })
      })
      .catch(err => setStatus({ text: err.message, error: true }))
  }, [selectedGraphId])

  // BQL: resolve cross-graph neighbor nodes + their parents whenever the active node changes.
  // Step 1 (WITH depth 1): all immediate neighbors across all graphs.
  // Step 2 (TO HIERARCHICAL depth 1): parent of each neighbor — used for disambiguation tooltip
  //   when many peers share the same name (e.g. multiple "Diagnoses" nodes under different L1 domains).
  useEffect(() => {
    setCrossGraphNodeMap({})
    setCrossGraphParentMap({})
    if (!activeNode || !selectedGraphId) return
    bqlQuery({
      graph: { id: selectedGraphId },
      starting: { node_id: activeNode.node_id },
      steps: [
        { direction: 'WITH', depth: 1, graphs: ['*'], collect: true },
        { direction: 'TO', link_types: ['HIERARCHICAL'], depth: 1, graphs: ['*'], collect: true },
      ],
      result: { format: 'LINK_NODE', include_seed: false },
    })
      .then(data => {
        const nodeMap = {}
        const parentMap = {}
        for (const item of data.results) {
          if (item._step === 1) {
            nodeMap[item.node.node_id] = item.node
          } else if (item._step === 2) {
            // item.node = parent; item.link.to_node_id = peer (child we traversed from)
            const peerId = item.link?.to_node_id
            if (peerId && !parentMap[peerId]) parentMap[peerId] = item.node.name
          }
        }
        setCrossGraphNodeMap(nodeMap)
        setCrossGraphParentMap(parentMap)
      })
      .catch(() => {}) // silent — UUID fallback still renders
  }, [activeNode, selectedGraphId])

  // All links touching the active node (for detail panel) — includes cross-graph links
  const activeLinks = useMemo(() => {
    if (!activeNode || !exportData) return []
    const all = [...(exportData.links ?? []), ...(exportData.cross_graph_links ?? [])]
    return all.filter(
      l => l.from_node_id === activeNode.node_id || l.to_node_id === activeNode.node_id
    )
  }, [activeNode, exportData])

  return (
    <>
      {!actorHandle && <LoginModal onLogin={handleLogin} />}
      <header className="header">
        <h1>Banyan</h1>
        <GraphPicker
          graphs={graphs}
          selectedId={selectedGraphId}
          onSelect={id => { setSelected(id); setSearchTerm(''); setNavHistory([]) }}
          loading={graphs.length === 0 && !status.error}
        />
        {loadingGraph && <div className="spinner" />}
        {actorHandle && (
          <div className="actor-badge">
            <span className="actor-badge-name" title={actorHandle}>{actorDisplayName}</span>
            <button className="actor-switch-btn" onClick={handleSwitchActor} title="Switch actor">⇄</button>
          </div>
        )}
        {navHistory.length > 0 && (
          <button className="nav-btn" onClick={navigateBack} title="Go back">
            ← Back
          </button>
        )}
        <button
          className={`nav-btn${rightPanelOpen && rightPanelTab === 'agent' ? ' nav-btn-active' : ''}`}
          onClick={() => {
            if (rightPanelOpen && rightPanelTab === 'agent') setRightPanelOpen(false)
            else { setRightPanelOpen(true); setRightPanelTab('agent') }
          }}
        >
          ✨ Agent
        </button>
        <button
          className={`nav-btn${rightPanelOpen && rightPanelTab === 'review' ? ' nav-btn-active' : ''}`}
          onClick={() => {
            if (rightPanelOpen && rightPanelTab === 'review') setRightPanelOpen(false)
            else { setRightPanelOpen(true); setRightPanelTab('review') }
          }}
        >
          ✓ Review
        </button>
        <span className={`header-status${status.error ? ' error' : ''}`}>
          {status.text}
        </span>
      </header>

      <div className="workspace">
        <aside className="sidebar" style={{ width: sidebarWidth }}>
          <div className="sidebar-search">
            <input
              type="search"
              placeholder="Search nodes…"
              value={searchTerm}
              onChange={e => { if (e.target.value) setActiveNode(null); setSearchTerm(e.target.value) }}
              disabled={!exportData}
            />
          </div>
          {exportData && (
            <div className="sidebar-meta">
              <span>{exportData.graph.name} · {exportData.nodes.filter(n => n.source_id !== '$ROOT$').length} nodes</span>
              <div className="tree-controls">
                <button className="tree-btn" onClick={() => nodeTreeRef.current?.collapseAll()} title="Collapse all">⊖</button>
                <button className="tree-btn" onClick={() => nodeTreeRef.current?.expandAll()} title="Expand all">⊕</button>
              </div>
            </div>
          )}
          {orphanCount > 0 && (
            <div className="sidebar-orphan-warn" title={`${orphanCount} node(s) have no inbound HIERARCHICAL path — graph structure is incomplete`}>
              ⚠ {orphanCount} orphaned node{orphanCount > 1 ? 's' : ''}
            </div>
          )}
          <NodeTree
            ref={nodeTreeRef}
            treeData={treeData}
            nodeCount={exportData?.nodes.length ?? 0}
            searchTerm={searchTerm}
            selectedId={activeNode?.node_id}
            onSelect={navigateToNode}
          />
        </aside>

        <div className="splitter" onMouseDown={onSplitterMouseDown} />

        <NodeDetail
          node={activeNode}
          links={activeLinks}
          nodeMap={nodeMap}
          crossGraphNodeMap={crossGraphNodeMap}
          crossGraphParentMap={crossGraphParentMap}
          graphMap={graphMap}
          nodeTypeMap={nodeTypeMap}
          hierarchicalIds={hierarchicalIds}
          relatedIds={relatedIds}
          symmetricIds={symmetricIds}
          onSelect={navigateToNode}
        />

        {rightPanelOpen && (
          <>
            <div className="splitter" onMouseDown={onRightSplitterMouseDown} />
            <div className="right-panel-col" style={{ width: rightPanelWidth }}>
              <div className="rp-tabbar">
                <button
                  className={`rp-tab${rightPanelTab === 'agent' ? ' rp-tab-active' : ''}`}
                  onClick={() => setRightPanelTab('agent')}
                >✨ Agent</button>
                <button
                  className={`rp-tab${rightPanelTab === 'review' ? ' rp-tab-active' : ''}`}
                  onClick={() => setRightPanelTab('review')}
                >✓ Review</button>
                <button className="rp-close" onClick={() => setRightPanelOpen(false)}>✕</button>
              </div>
              <div className="rp-pane" style={{ display: rightPanelTab === 'agent' ? 'flex' : 'none' }}>
                <ChatPanel
                  sessionId={sessionId}
                  context={{
                    graph_id:              selectedGraphId,
                    graph_name:            exportData?.graph?.name ?? null,
                    node_id:               activeNode?.node_id ?? null,
                    node_name:             activeNode?.name ?? null,
                    node_source_id:        activeNode?.source_id ?? null,
                    operator_handle:       actorHandle,
                    operator_display_name: actorDisplayName,
                  }}
                  onAction={handleAgentAction}
                />
              </div>
              <div className="rp-pane" style={{ display: rightPanelTab === 'review' ? 'flex' : 'none' }}>
                <ReviewPanel
                  graphs={graphs}
                  relatedTypes={relatedTypes}
                  graphMap={graphMap}
                  actorHandle={actorHandle}
                  onNavigate={navigateToNode}
                  onReveal={revealInTree}
                  onMutated={refreshGraph}
                />
              </div>
            </div>
          </>
        )}
      </div>
    </>
  )
}
