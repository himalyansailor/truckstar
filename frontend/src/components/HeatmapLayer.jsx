import { useEffect, useRef } from 'react'
import { useMap } from 'react-leaflet'
import HeatCanvas from '../heatLayer'

// react wrapper around the canvas layer in heatLayer.js
function HeatmapLayer({ heat, hour }) {
  const map = useMap()
  const layerRef = useRef(null)

  useEffect(() => {
    if (!heat) return
    // circles a bit wider than the gap between points (1.3x) so they overlap, no holes
    const layer = new HeatCanvas({ radiusMi: heat.spacing_mi * 1.3 })
    layer.addTo(map)
    layerRef.current = layer
    return () => {
      map.removeLayer(layer)
      layerRef.current = null
    }
  }, [map, heat])

  // update colors when slider moves
  useEffect(() => {
    if (!heat || !layerRef.current) return
    // the forecast is hourly but the slider moves in 0.1 h steps, so mix the 2 nearest
    // hours: at 5.3 h it's 70% of hour 5 + 30% of hour 6. smooth instead of jumping every hour
    const h1 = Math.min(Math.max(Math.floor(hour), 0), 48)
    const h2 = Math.min(h1 + 1, 48)
    const t = hour - h1
    const pts = heat.points.map((p, i) => {
      const v = heat.values[h1][i] * (1 - t) + heat.values[h2][i] * t
      return [p[0], p[1], v]
    })
    layerRef.current.setData(pts)
  }, [heat, hour])

  return null
}

export default HeatmapLayer
