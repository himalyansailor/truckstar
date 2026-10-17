import { Fragment, memo, useEffect, useMemo } from 'react'
import { MapContainer, TileLayer, Polyline, CircleMarker, Marker, Tooltip, useMap } from 'react-leaflet'
import L from 'leaflet'
import HeatmapLayer from './HeatmapLayer'
import { RISK_COLORS, TILES, formatDuration, formatTime } from '../constants'

const truckIcon = L.divIcon({ className: 'truck-icon', html: '🚚', iconSize: [28, 28], iconAnchor: [14, 14] })

function milesAlong(line) {
  // cumulative miles at each point (haversine, same as the backend)
  const out = [0]
  for (let i = 1; i < line.length; i++) {
    const [lat1, lon1] = line[i - 1]
    const [lat2, lon2] = line[i]
    const dLat = ((lat2 - lat1) * Math.PI) / 180
    const dLon = ((lon2 - lon1) * Math.PI) / 180
    const a =
      Math.sin(dLat / 2) ** 2 +
      Math.cos((lat1 * Math.PI) / 180) * Math.cos((lat2 * Math.PI) / 180) * Math.sin(dLon / 2) ** 2
    out.push(out[i - 1] + 2 * 3958.8 * Math.asin(Math.sqrt(a)))
  }
  return out
}

// truck at the slider time. two steps, time -> mile -> position:
// 1. the checkpoints have a mile and an ETA, so find the two checkpoints the time is
//    between and assume a steady speed between them. e.g. checkpoint at mile 25 at 10:00,
//    mile 50 at 10:30, slider at 10:12 -> 40% of the way -> mile 35
// 2. walk along the drawn route line to that mile, so the truck stays on the road instead
//    of cutting straight between checkpoints (same idea as points_every_n_miles in the backend)
function TruckMarker({ route, time }) {
  const miles = useMemo(() => milesAlong(route.geometry), [route])

  const cps = route.checkpoints
  const etas = cps.map((c) => new Date(c.eta).getTime())
  let mile = 0 // before departure: at the start
  if (time >= etas[etas.length - 1]) {
    mile = cps[cps.length - 1].mile // arrived: at the end
  } else if (time > etas[0]) {
    let i = 0
    while (etas[i + 1] < time) i++ // checkpoint i is the last one passed
    const share = (time - etas[i]) / (etas[i + 1] - etas[i])
    mile = cps[i].mile + (cps[i + 1].mile - cps[i].mile) * share
  }
  // the drawn line has fewer points than the real route (the backend thins it), cutting
  // corners, so it's a bit shorter. scale the mile to it, else the truck reaches the end early
  mile = (mile * miles[miles.length - 1]) / cps[cps.length - 1].mile

  // find the two line points around that mile and go the right share of the way between them
  const g = route.geometry
  let j = 0
  while (j < miles.length - 2 && miles[j + 1] < mile) j++
  const seg = miles[j + 1] - miles[j]
  const f = seg > 0 ? Math.min(1, Math.max(0, (mile - miles[j]) / seg)) : 0
  const pos = [g[j][0] + (g[j + 1][0] - g[j][0]) * f, g[j][1] + (g[j + 1][1] - g[j][1]) * f]

  return <Marker position={pos} icon={truckIcon} interactive={false} />
}

// split the drawn line into stretches between checkpoints, each with the risk of that
// stretch (worse of its two ends, same rule as route_summary in the backend), so the line
// can be coloured like traffic. stretches next to each other with the same risk are
// merged so there are fewer lines to draw.
// the line has no checkpoints in it, only their miles, so: walk the line point by point,
// and when the next point is past the next checkpoint's mile, cut the line there
function riskStretches(route) {
  const g = route.geometry
  const cps = route.checkpoints
  const miles = milesAlong(g)
  const scale = miles[miles.length - 1] / cps[cps.length - 1].mile // drawn line is thinned, a bit shorter

  const out = []
  let current = null
  let j = 0
  for (let i = 0; i < cps.length - 1; i++) {
    const risk = Math.max(cps[i].risk, cps[i + 1].risk)
    const end = cps[i + 1].mile * scale // where this stretch ends on the drawn line
    const pts = [] // line points inside this stretch
    while (j < g.length - 1 && miles[j + 1] <= end) {
      j++
      pts.push(g[j])
    }
    // the checkpoint is between point j and j + 1: add the point at the exact checkpoint
    // mile, so the colour changes there and not at the nearest line point
    let cut = g[j]
    if (j < g.length - 1 && miles[j + 1] > miles[j]) {
      const f = (end - miles[j]) / (miles[j + 1] - miles[j])
      cut = [g[j][0] + (g[j + 1][0] - g[j][0]) * f, g[j][1] + (g[j + 1][1] - g[j][1]) * f]
    }
    if (!current) {
      current = { risk, points: [g[0]] }
    } else if (risk !== current.risk) {
      // new colour: close the old stretch, start the new one where the old ended (no gap)
      out.push(current)
      current = { risk, points: [current.points[current.points.length - 1]] }
    }
    current.points.push(...pts, cut)
  }
  if (current) out.push(current)
  return out
}

// small label on the route ("B · 16h 28m"), like the time bubbles on google maps
function routeLabelIcon(r, isSelected) {
  return L.divIcon({
    className: '',
    html: `<div class="route-pill${isSelected ? ' selected' : ''}">${r.label.replace('Route ', '')} · ${formatDuration(r.duration_hr)}</div>`,
    iconSize: null,
    iconAnchor: [0, 0],
  })
}

// zooms map to the routes when a new plan comes in
function ZoomToRoutes({ plan }) {
  const map = useMap()
  useEffect(() => {
    if (plan) map.fitBounds(L.latLngBounds(plan.routes.flatMap((r) => r.geometry)), { padding: [40, 40] })
  }, [map, plan])
  return null
}

// route lines + checkpoints. memo so dragging the slider (hour changes) doesn't re-render them
const RouteLines = memo(function RouteLines({ plan, selected, onSelect, onCheckpointClick }) {
  if (!plan) return null
  // put selected route at the end so its drawn on top
  const selectedRoute = plan.routes.find((r) => r.id === selected)
  const routesToDraw = [...plan.routes.filter((r) => r.id !== selected), selectedRoute]

  return (
    <>
      {routesToDraw.map((r) => {
        const isSelected = r.id === selected
        const select = { click: () => onSelect(r.id) }
        return (
          <Fragment key={'route' + r.id + isSelected}>
            {/* outline under the coloured line: dark for the selected route, grey for the others */}
            <Polyline
              positions={r.geometry}
              pathOptions={{ color: isSelected ? '#1e293b' : '#64748b', weight: isSelected ? 10 : 6, opacity: isSelected ? 0.9 : 0.35 }}
              eventHandlers={select}
            />
            {/* the line itself is coloured by risk on each stretch, like traffic on google maps */}
            {riskStretches(r).map((st, k) => (
              <Polyline
                key={k}
                positions={st.points}
                pathOptions={{ color: RISK_COLORS[st.risk], weight: isSelected ? 6 : 3, opacity: isSelected ? 1 : 0.5 }}
                eventHandlers={select}
              />
            ))}
            <Marker
              // A / B / C at 35% / 50% / 65% of their line so the labels don't sit on top of each other
              position={r.geometry[Math.floor(r.geometry.length * [0.35, 0.5, 0.65][r.id])]}
              icon={routeLabelIcon(r, isSelected)}
              eventHandlers={select}
              zIndexOffset={isSelected ? 1000 : 0}
            />
          </Fragment>
        )
      })}

      {/* checkpoints only on the selected route, small so the line colour still shows */}
      {selectedRoute.checkpoints.map((c, i) => (
        <CircleMarker
          key={selectedRoute.id + '-' + i}
          center={[c.lat, c.lon]}
          radius={4}
          pathOptions={{ color: 'white', weight: 1.5, fillColor: RISK_COLORS[c.risk], fillOpacity: 1 }}
          eventHandlers={{ click: () => onCheckpointClick(selectedRoute.id, i) }}
        >
          {/* hover: quick look. click: selects it and moves the truck there, details in the panel */}
          <Tooltip direction="top" offset={[0, -6]}>
            {selectedRoute.label} · mile {Math.round(c.mile)} · {formatTime(c.eta)} · <b>{c.risk_label}</b>
          </Tooltip>
        </CircleMarker>
      ))}
    </>
  )
})

function RouteMap({ plan, selected, onSelect, onCheckpointClick, heat, hour, showHeat, truckRoute, truckTime, checkpoint }) {
  return (
    <MapContainer center={[39.5, -98.5]} zoom={4} style={{ height: '100%' }} preferCanvas={true}>
      <TileLayer url={TILES.url} attribution={TILES.attribution} className="tiles" />
      <ZoomToRoutes plan={plan} />
      {heat && showHeat && <HeatmapLayer heat={heat} hour={hour} />}
      <RouteLines plan={plan} selected={selected} onSelect={onSelect} onCheckpointClick={onCheckpointClick} />
      {/* ring around the selected checkpoint */}
      {checkpoint && (
        <CircleMarker
          center={[checkpoint.lat, checkpoint.lon]}
          radius={11}
          pathOptions={{ color: '#111', weight: 3, fill: false }}
          interactive={false}
        />
      )}
      {truckRoute && truckTime && <TruckMarker route={truckRoute} time={truckTime} />}
    </MapContainer>
  )
}

export default RouteMap
