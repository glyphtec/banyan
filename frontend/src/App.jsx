import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import './App.css'
import { listGraphs, exportGraph, getLinkTypes, getNodeTypes } from './api'
import { buildHierarchicalFamily, buildTree } from './treeUtils'
import { GraphPicker } from './components/GraphPicker'
import { NodeTree } from './components/NodeTree'
import { NodeDetail } from './components/NodeDetail'

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
  const [sidebarWidth, setSidebarWidth] = useState(320)
  const nodeTreeRef = useRef(null)
  const dragging = useRef(false)

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
      })
      .catch(err => setStatus({ text: err.message, error: true }))
      .finally(() => setLoadingGraph(false))
  }, [selectedGraphId])

  const hierarchicalIds = useMemo(() => buildHierarchicalFamily(linkTypes), [linkTypes])
  const relatedIds = useMemo(() => new Set(relatedTypes.map(lt => lt.link_type_id)), [relatedTypes])

  const treeData = useMemo(() => {
    if (!exportData) return []
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
      <header className="header">
        <h1>Banyan</h1>
        <GraphPicker
          graphs={graphs}
          selectedId={selectedGraphId}
          onSelect={id => { setSelected(id); setSearchTerm('') }}
          loading={graphs.length === 0 && !status.error}
        />
        {loadingGraph && <div className="spinner" />}
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
              <span>{exportData.graph.name} · {exportData.nodes.length} nodes</span>
              <div className="tree-controls">
                <button className="tree-btn" onClick={() => nodeTreeRef.current?.collapseAll()} title="Collapse all">⊖</button>
                <button className="tree-btn" onClick={() => nodeTreeRef.current?.expandAll()} title="Expand all">⊕</button>
              </div>
            </div>
          )}
          <NodeTree
            ref={nodeTreeRef}
            treeData={treeData}
            nodeCount={exportData?.nodes.length ?? 0}
            searchTerm={searchTerm}
            selectedId={activeNode?.node_id}
            onSelect={setActiveNode}
          />
        </aside>

        <div className="splitter" onMouseDown={onSplitterMouseDown} />

        <NodeDetail
          node={activeNode}
          links={activeLinks}
          nodeMap={nodeMap}
          graphMap={graphMap}
          nodeTypeMap={nodeTypeMap}
          hierarchicalIds={hierarchicalIds}
          relatedIds={relatedIds}
          onSelect={setActiveNode}
        />
      </div>
    </>
  )
}
