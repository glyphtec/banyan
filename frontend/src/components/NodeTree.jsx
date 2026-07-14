import React, { useRef, useLayoutEffect, useState, useEffect, useImperativeHandle, forwardRef } from 'react'
import { Tree } from 'react-arborist'

function Node({ node, style, dragHandle }) {
  const hasKids = node.children && node.children.length > 0
  const toggle = hasKids ? (node.isOpen ? '▾' : '▸') : '·'
  return (
    <div
      className={`tree-node${node.isSelected ? ' selected' : ''}`}
      style={style}
      ref={dragHandle}
      onClick={() => node.toggle()}
    >
      <span className="toggle">{toggle}</span>
      <span className="label" title={node.data.name}>{node.data.name}</span>
    </div>
  )
}

export const NodeTree = forwardRef(function NodeTree(
  { treeData, nodeCount, onSelect, searchTerm, selectedId },
  ref
) {
  const wrapRef = useRef(null)
  const treeRef = useRef(null)
  const prevSearchTerm = useRef(searchTerm)
  const [dims, setDims] = useState({ width: 300, height: 400 })

  useImperativeHandle(ref, () => ({
    collapseAll: () => treeRef.current?.closeAll?.(),
    expandAll:   () => treeRef.current?.openAll?.(),
    // Double rAF: first frame lets React commit the new tree data;
    // second frame lets react-arborist update its virtual list before we scroll.
    revealNode:  (id) => {
      if (!id) return
      requestAnimationFrame(() => requestAnimationFrame(() => {
        treeRef.current?.select?.(id)        // sync internal selection state
        treeRef.current?.openParents?.(id)
        treeRef.current?.scrollTo?.(id, 'center')
      }))
    },
  }))

  // When search is cleared and a node is pinned, open its ancestor path and scroll to it.
  useEffect(() => {
    const wasFiltered = Boolean(prevSearchTerm.current)
    prevSearchTerm.current = searchTerm
    if (wasFiltered && !searchTerm && selectedId && treeRef.current) {
      setTimeout(() => {
        treeRef.current?.openParents?.(selectedId)
        treeRef.current?.scrollTo?.(selectedId, 'center')
      }, 50)
    }
  }, [searchTerm, selectedId])

  useLayoutEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect
      setDims({ width: Math.floor(width), height: Math.floor(height) })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  if (!treeData || treeData.length === 0) {
    return (
      <div className="tree-wrap" ref={wrapRef}>
        <div className="loading"><span>No tree data</span></div>
      </div>
    )
  }

  return (
    <div className="tree-wrap" ref={wrapRef}>
      <Tree
        ref={treeRef}
        data={treeData}
        width={dims.width}
        height={dims.height}
        rowHeight={26}
        indent={18}
        searchTerm={searchTerm}
        selection={selectedId ? [selectedId] : []}
        searchMatch={(node, term) =>
          node.data.name.toLowerCase().includes(term.toLowerCase())
        }
        onSelect={nodes => nodes.length > 0 && onSelect(nodes[0].data.data)}
        disableDrag
        disableDrop
        openByDefault={false}
      >
        {Node}
      </Tree>
    </div>
  )
})
