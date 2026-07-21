/**
 * Given link_types already filtered to the HIERARCHICAL family
 * (via GET /link-types?root=HIERARCHICAL), return a Set of their IDs.
 * Kept as a function so the call site is unchanged if the API changes.
 */
export function buildHierarchicalFamily(linkTypes) {
  return new Set(linkTypes.map(lt => lt.link_type_id))
}

/**
 * Convert a flat export {nodes, links} into nested tree data for react-arborist.
 * Only follows links whose link_type_id is in hierarchicalIds.
 * Returns { tree, orphanCount } where orphanCount is the number of content
 * nodes (non-$ROOT$) that have no inbound HIERARCHICAL link at all.
 * A non-zero count means nodes are structurally disconnected.
 */
export function buildTree(nodes, links, hierarchicalIds) {
  // Strip $ROOT$ from the display nodes — it is a technical sentinel node
  // bootstrapped on every graph.  Its outbound links are still used to
  // determine tree structure and the orphan count.
  const displayNodes = nodes.filter(n => n.source_id !== '$ROOT$')
  const nodeIds = new Set(displayNodes.map(n => n.node_id))
  // Exclude links whose parent is not in the visible node set (e.g. $ROOT$ is
  // stripped from the export nodes but its outbound links are still present).
  const hierarchicalLinks = links.filter(
    l => hierarchicalIds.has(l.link_type_id) && nodeIds.has(l.from_node_id)
  )

  const childSet = new Set(hierarchicalLinks.map(l => l.to_node_id))
  const childrenOf = {}
  for (const l of hierarchicalLinks) {
    if (!childrenOf[l.from_node_id]) childrenOf[l.from_node_id] = []
    childrenOf[l.from_node_id].push(l.to_node_id)
  }

  const nodeMap = Object.fromEntries(displayNodes.map(n => [n.node_id, n]))

  function build(nodeId) {
    const n = nodeMap[nodeId]
    if (!n) return null
    const kids = (childrenOf[nodeId] || []).map(build).filter(Boolean)
    return {
      id: nodeId,
      name: n.name,
      data: n,
      children: kids.length ? kids : undefined,
    }
  }

  const roots = displayNodes.filter(n => !childSet.has(n.node_id))
  const tree  = roots.map(n => build(n.node_id)).filter(Boolean)

  // orphanCount: nodes that have no inbound HIERARCHICAL link at all,
  // including links from $ROOT$ (which is stripped from the export nodes but
  // whose outbound links are present in the links array).
  // A node with no to_node_id entry in any hierarchical link is structurally
  // disconnected from the graph hierarchy.
  const hasInboundHierarchical = new Set(
    links.filter(l => hierarchicalIds.has(l.link_type_id)).map(l => l.to_node_id)
  )
  const orphanCount = displayNodes.filter(n => !hasInboundHierarchical.has(n.node_id)).length

  return { tree, orphanCount }
}
