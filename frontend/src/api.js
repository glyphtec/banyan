async function _get(path) {
  const r = await fetch(path)
  if (!r.ok) throw new Error(`GET ${path} → ${r.status} ${r.statusText}`)
  return r.json()
}

async function _post(path, body) {
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`POST ${path} → ${r.status} ${r.statusText}`)
  return r.json()
}

async function _postAs(path, body, actorHandle) {
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Actor-Id': actorHandle || 'anonymous' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`POST ${path} → ${r.status} ${r.statusText}`)
  return r.json()
}

async function _patchAs(path, body, actorHandle) {
  const r = await fetch(path, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', 'X-Actor-Id': actorHandle || 'anonymous' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`PATCH ${path} → ${r.status} ${r.statusText}`)
  return r.json()
}

export const listGraphs     = ()       => _get('/api/v1/graphs')
export const exportGraph    = (graphId) => _get(`/api/v1/graphs/${graphId}/export?include_cross_graph_links=true`)
export const getLinkTypes   = (root)   => _get(`/api/v1/link-types${root ? `?root=${encodeURIComponent(root)}` : ''}`)
export const getNodeTypes   = ()       => _get('/api/v1/node-types')
export const bqlQuery       = (body)   => _post('/api/v1/query', body)
export const listActors     = ()       => _get('/api/v1/actors')
export const registerActor  = (body)   => _post('/api/v1/actors', body)
export const executeBatch   = (body, actorHandle) => _postAs('/api/v1/graphs/batch', body, actorHandle)
export const updateLink     = (linkId, body, actorHandle) => _patchAs(`/api/v1/links/${linkId}`, body, actorHandle)
