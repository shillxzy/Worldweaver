/**
 * Force-directed layout (Fruchterman–Reingold) for the world graphs.
 * Nodes with a saved position stay fixed; only new nodes are placed, so the author's
 * manual arrangement is preserved. Deterministic: same input → same layout.
 */
export type Point = { x: number; y: number }

export function forceLayout(
  ids: string[],
  edges: [string, string][],
  fixed: Record<string, Point> = {},
  options: { width?: number; height?: number; iterations?: number } = {},
): Record<string, Point> {
  const n = ids.length
  const width = options.width ?? Math.max(800, 220 * Math.sqrt(n))
  const height = options.height ?? Math.max(600, 170 * Math.sqrt(n))
  const iterations = options.iterations ?? 300
  const k = Math.min(260, Math.sqrt((width * height) / Math.max(1, n)) * 0.9)
  const pos: Record<string, Point> = {}

  // Initial positions: saved ones, otherwise a circle (deterministic order).
  ids.forEach((id, i) => {
    const angle = (2 * Math.PI * i) / Math.max(1, n)
    pos[id] = fixed[id] ? { ...fixed[id] } : { x: width / 2 + (width / 3) * Math.cos(angle), y: height / 2 + (height / 3) * Math.sin(angle) }
  })
  const movable = ids.filter((id) => !fixed[id])
  if (movable.length === 0) return pos

  const links = edges.filter(([a, b]) => a !== b && pos[a] && pos[b])
  let temperature = width / 8
  for (let step = 0; step < iterations; step++) {
    const disp: Record<string, Point> = {}
    for (const id of ids) disp[id] = { x: 0, y: 0 }
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const a = ids[i], b = ids[j]
        let dx = pos[a].x - pos[b].x
        let dy = pos[a].y - pos[b].y
        let dist = Math.hypot(dx, dy)
        if (dist < 0.01) { dx = 0.01 * (i - j); dy = 0.01; dist = Math.hypot(dx, dy) }
        if (dist > 2.5 * k) continue // far-away nodes no longer push each other apart
        const force = (k * k) / dist
        disp[a].x += (dx / dist) * force; disp[a].y += (dy / dist) * force
        disp[b].x -= (dx / dist) * force; disp[b].y -= (dy / dist) * force
      }
    }
    for (const [a, b] of links) {
      const dx = pos[a].x - pos[b].x
      const dy = pos[a].y - pos[b].y
      const dist = Math.max(0.01, Math.hypot(dx, dy))
      const force = (dist * dist) / k
      disp[a].x -= (dx / dist) * force; disp[a].y -= (dy / dist) * force
      disp[b].x += (dx / dist) * force; disp[b].y += (dy / dist) * force
    }
    for (const id of movable) {
      // mild gravity towards the centre keeps disconnected nodes on screen
      disp[id].x += (width / 2 - pos[id].x) * 0.15
      disp[id].y += (height / 2 - pos[id].y) * 0.15
      const len = Math.max(0.01, Math.hypot(disp[id].x, disp[id].y))
      pos[id].x += (disp[id].x / len) * Math.min(len, temperature)
      pos[id].y += (disp[id].y / len) * Math.min(len, temperature)
    }
    temperature = Math.max(1, temperature * 0.97)
  }
  for (const id of movable) pos[id] = { x: Math.round(pos[id].x), y: Math.round(pos[id].y) }
  return pos
}
