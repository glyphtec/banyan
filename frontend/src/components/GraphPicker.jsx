import React from 'react'

export function GraphPicker({ graphs, selectedId, onSelect, loading }) {
  return (
    <div className="graph-picker">
      <label htmlFor="graph-select">Graph</label>
      <select
        id="graph-select"
        value={selectedId ?? ''}
        disabled={loading || graphs.length === 0}
        onChange={e => onSelect(e.target.value)}
      >
        <option value="" disabled>
          {loading ? 'Loading…' : graphs.length === 0 ? 'No graphs' : '— select —'}
        </option>
        {graphs.map(g => (
          <option key={g.graph_id} value={g.graph_id}>
            {g.name}
          </option>
        ))}
      </select>
    </div>
  )
}
