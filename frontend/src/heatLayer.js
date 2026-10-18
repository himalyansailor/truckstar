import L from 'leaflet'
import { RISK_COLORS } from './constants'

// custom heat layer
// first used leaflet.heat but it adds up overlapping points so even "Low" weather
// showed as red everywhere. this one colors each point by its own value instead.
// the L.Layer / canvas positioning part follows leaflet's custom layer pattern

// '#3fb950' -> [63, 185, 80]: the red, green, blue parts of each risk colour, so two
// colours can be mixed by mixing the numbers
const RGB = RISK_COLORS.map((h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)))

function colorFor(v) {
  // v is 0..1 from the backend (score / 4). back to 0..4: the whole part is the level, the
  // rest is how far towards the next level. 1.5 -> halfway between yellow (1) and orange (2)
  const x = Math.min(Math.max(v, 0), 1) * 4
  const i = Math.min(Math.floor(x), 3)
  const f = x - i
  const a = RGB[i], b = RGB[i + 1]
  return [0, 1, 2].map((k) => Math.round(a[k] + (b[k] - a[k]) * f))
}

const HeatCanvas = L.Layer.extend({
  // opts.radiusMi = how wide each point's circle is, in miles
  initialize(opts) {
    this._pts = []
    this._radiusMi = opts?.radiusMi || 20
  },

  // leaflet calls this when the layer is added: make the canvas, redraw on pan / resize
  onAdd(map) {
    this._map = map
    this._canvas = L.DomUtil.create('canvas', 'heat-canvas leaflet-zoom-hide')
    this._canvas.style.pointerEvents = 'none'
    map.getPanes().overlayPane.appendChild(this._canvas)
    map.on('moveend resize', this._reset, this)
    this._reset()
  },

  // leaflet calls this when the layer is removed
  onRemove(map) {
    L.DomUtil.remove(this._canvas)
    map.off('moveend resize', this._reset, this)
  },

  // new values ([[lat, lon, 0..1], ...], e.g. when the slider moves) -> redraw
  setData(pts) {
    this._pts = pts
    if (this._map) this._draw()
  },

  // after a pan or resize: move the canvas back over the visible map, resize, redraw
  _reset() {
    const map = this._map
    const size = map.getSize()
    L.DomUtil.setPosition(this._canvas, map.containerPointToLayerPoint([0, 0]))
    this._canvas.width = size.x
    this._canvas.height = size.y
    this._draw()
  },

  // paint every point as a soft circle in its risk colour
  _draw() {
    const map = this._map
    const ctx = this._canvas.getContext('2d')
    const w = this._canvas.width, h = this._canvas.height
    ctx.clearRect(0, 0, w, h)
    if (!this._pts.length) return

    // each point is drawn as a soft circle `radiusMi` miles wide, so neighbouring points
    // overlap and the corridor looks continuous. pixels per mile change with the zoom, so
    // measure it: take the map centre and a point radiusMi north of it (1 deg of latitude
    // ~ 69 mi), the pixels between them = the radius. at least 6 px when zoomed far out
    const c = map.getCenter()
    const p1 = map.latLngToContainerPoint(c)
    const p2 = map.latLngToContainerPoint([c.lat + this._radiusMi / 69, c.lng])
    const r = Math.max(6, Math.abs(p1.y - p2.y))

    // low first so the scary stuff ends up drawn on top
    const sorted = [...this._pts].sort((a, b) => a[2] - b[2])
    for (const [lat, lon, v] of sorted) {
      const p = map.latLngToContainerPoint([lat, lon])
      if (p.x < -r || p.y < -r || p.x > w + r || p.y > h + r) continue // off screen, skip
      const [R, G, B] = colorFor(v)
      // calm weather stays faint, bad weather gets loud: 0.12 opacity at Low, up to 0.67
      // from v 0.625 (score 2.5, between High and Severe) up, so the map under it stays readable
      const alpha = 0.12 + 0.55 * Math.min(1, v * 1.6)
      // full colour in the middle, fading to transparent at the edge
      const g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, r)
      g.addColorStop(0, `rgba(${R},${G},${B},${alpha})`)
      g.addColorStop(1, `rgba(${R},${G},${B},0)`)
      ctx.fillStyle = g
      ctx.fillRect(p.x - r, p.y - r, r * 2, r * 2)
    }
  },
})

export default HeatCanvas
