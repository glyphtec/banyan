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
 * Returns array of root node objects: { id, name, data, children? }
 */
export function buildTree(nodes, links, hierarchicalIds) {
  const nodeIds = new Set(nodes.map(n => n.node_id))
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

  const nodeMap = Object.fromEntries(nodes.map(n => [n.node_id, n]))

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

  const roots = nodes.filter(n => !childSet.has(n.node_id))
  return roots.map(n => build(n.node_id)).filter(Boolean)
}
