async function _get(path) {
  const r = await fetch(path)
  if (!r.ok) throw new Error(`GET ${path} → ${r.status} ${r.statusText}`)
  return r.json()
}

export const listGraphs   = ()         => _get('/api/v1/graphs')
export const exportGraph  = (graphId)  => _get(`/api/v1/graphs/${graphId}/export`)
export const getLinkTypes = (root)     => _get(`/api/v1/link-types${root ? `?root=${encodeURIComponent(root)}` : ''}`)
export const getNodeTypes = ()         => _get('/api/v1/node-types')
