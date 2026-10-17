import { useCallback, useEffect, useRef, useState } from 'react'
import TripForm from './components/TripForm'
import RouteCards from './components/RouteCards'
import RouteMap from './components/RouteMap'
import TimeSlider from './components/TimeSlider'
import CheckpointPanel from './components/CheckpointPanel'
import Legend from './components/Legend'
import { API_URL } from './constants'
import './App.css'

async function postJson(path, body) {
  const res = await fetch(API_URL + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.error || 'Something went wrong')
  return data
}

function errorText(err) {
  // fetch throws TypeError when the server can't be reached at all
  return err instanceof TypeError ? 'Could not reach the server' : err.message
}

// slider hour 0 = the departure hour, rounded down in UTC like the backend does for the
// heatmap: milliseconds / 3,600,000 = hours, floor, back to milliseconds.
// (rounding in local time was 30 min off in india, IST is UTC+5:30)
function startOf(plan) {
  return Math.floor(new Date(plan.depart_at).getTime() / 3600000) * 3600000
}

// a route's heatmap is reused when the full plan has the same route as the quick one.
// rows = corridor width (1 = ±15 mi, 2 = ±30 mi), a different width is a different heatmap
function heatKey(route, rows) {
  return route.label + ':' + route.distance_mi + ':' + rows
}

function App() {
  const [plan, setPlan] = useState(null)
  const [partial, setPartial] = useState(false) // only the first route so far
  const [selected, setSelected] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const [heatByRoute, setHeatByRoute] = useState({}) // heatKey -> heatmap for that route
  const [heatErrors, setHeatErrors] = useState({}) // heatKey -> error, shown in the slider box
  const [corridor, setCorridor] = useState(1) // heatmap rows each side of the route, user picks
  const [hour, setHour] = useState(0)
  const [showHeat, setShowHeat] = useState(true)
  const [playing, setPlaying] = useState(false)

  // so answers from an older search don't overwrite a newer one
  const requestId = useRef(0)
  const heatRequested = useRef(new Set())
  const lastForm = useRef(null) // for the heatmap retry button

  async function planTrip(form) {
    const id = ++requestId.current
    lastForm.current = form
    setLoading(true)
    setError('')
    setPlan(null)
    setPartial(false)
    setHeatByRoute({})
    setHeatErrors({})
    heatRequested.current = new Set()
    setHour(0)
    setPlaying(false)

    // tomtom takes ~8 s for the 3 routes but ~3 s for just the main one, so ask for both
    // at the same time and show the main route as soon as it's back
    let fullDone = false
    postJson('/api/plan/', { ...form, quick: true })
      .then((data) => {
        if (id !== requestId.current || fullDone) return
        setPlan(data)
        setSelected(data.recommended)
        setPartial(true)
      })
      .catch(() => {}) // the full request shows the error

    try {
      const data = await postJson('/api/plan/', form)
      fullDone = true
      if (id !== requestId.current) return
      setPlan(data)
      setSelected(data.recommended)
      // quick plan had only route A selected, start over if the recommended one is another route
      if (data.recommended !== 0) setHour(0)
      setPartial(false)
      setLoading(false)
    } catch (err) {
      if (id !== requestId.current) return
      setError(errorText(err))
      setPartial(false)
      setLoading(false)
    }
  }

  // one heatmap per route, loaded when that route is selected (see the effect below).
  // loading all 3 up front was ~380 weather lookups per trip and hit open meteo's free
  // limit, most people only look at 1 or 2 routes
  function loadHeatmap(form, route, id, rows) {
    const key = heatKey(route, rows)
    heatRequested.current.add(key)
    setHeatErrors((prev) => ({ ...prev, [key]: null }))
    const line = route.checkpoints.map((c) => [c.lat, c.lon])
    postJson('/api/heatmap/', { depart_at: form.depart_at, weight: form.weight, lines: [line], rows: rows })
      .then((h) => {
        if (id === requestId.current) setHeatByRoute((prev) => ({ ...prev, [key]: h }))
      })
      .catch((err) => {
        // only this route's heatmap failed, the routes + risk are fine, so no big red error
        if (id === requestId.current) setHeatErrors((prev) => ({ ...prev, [key]: errorText(err) }))
      })
  }

  // play button: moves the slider until the truck arrives (it used to keep going to 48h
  // after the trip was over). speed: 1 forecast hour per second, faster for long trips so
  // the whole trip never takes more than ~20 s (a 12 h trip = 12 s, 48 h = 20 s)
  const endHourRef = useRef(48)
  useEffect(() => {
    if (!playing) return
    let last = performance.now()
    let raf
    const tick = (now) => {
      // move by the real time since the last frame (dt seconds) x hours per second, so
      // the speed is the same on a 60 Hz and a 120 Hz screen.
      // first frame's timestamp can be a bit before `last`, don't go backwards below 0
      const dt = Math.max(0, now - last) / 1000
      last = now
      const hoursPerSecond = Math.max(1, endHourRef.current / 20)
      setHour((h) => Math.min(h + dt * hoursPerSecond, endHourRef.current))
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [playing])

  // picking another route (card or line on the map) starts its truck from the departure.
  // otherwise the truck kept the old route's time and finished that trip first. keeps
  // playing if it was playing
  const selectRoute = useCallback(
    (id) => {
      if (id === selected) return
      setSelected(id)
      setHour(0)
    },
    [selected]
  )

  // clicking a checkpoint (or the panel arrows) moves the slider to its ETA, so the truck
  // jumps there and it becomes the selected checkpoint. one source of truth: the hour
  const selectCheckpoint = useCallback(
    (routeId, i) => {
      const route = plan.routes.find((r) => r.id === routeId)
      const c = route.checkpoints[Math.min(Math.max(i, 0), route.checkpoints.length - 1)]
      const h = (new Date(c.eta).getTime() - startOf(plan)) / 3600000
      setSelected(routeId)
      setPlaying(false)
      setHour(Math.min(Math.max(h, 0), 48))
    },
    [plan]
  )

  const selectedRoute = plan && plan.routes.find((r) => r.id === selected)
  const heat = selectedRoute ? heatByRoute[heatKey(selectedRoute, corridor)] : null

  // load the selected route's heatmap (for the chosen corridor width) the first time it's needed
  useEffect(() => {
    if (!selectedRoute || !lastForm.current) return
    if (heatRequested.current.has(heatKey(selectedRoute, corridor))) return
    loadHeatmap(lastForm.current, selectedRoute, requestId.current, corridor)
  }, [selectedRoute, corridor])
  // time the slider points at, the truck marker shows where the selected route's truck is then
  const truckTime = plan ? startOf(plan) + hour * 3600 * 1000 : null

  // slider hour when the selected route's truck arrives (the slider only goes to 48h)
  const endHour = selectedRoute
    ? Math.min(48, (new Date(selectedRoute.arrive_at).getTime() - startOf(plan)) / 3600000)
    : 48
  const arrived = hour >= endHour - 0.01

  useEffect(() => {
    endHourRef.current = endHour
  }, [endHour])

  // stop playing when the truck gets there
  useEffect(() => {
    if (playing && arrived) setPlaying(false)
  }, [playing, arrived])

  function togglePlay() {
    if (!playing && arrived) setHour(0) // play again after arriving = start over
    setPlaying(!playing)
  }

  // selected checkpoint = the last one the truck has reached at the slider time
  // (1 s slack so clicking a checkpoint lands on it and not the one before)
  let cpIndex = 0
  if (selectedRoute) {
    selectedRoute.checkpoints.forEach((c, i) => {
      if (new Date(c.eta).getTime() <= truckTime + 1000) cpIndex = i
    })
  }

  return (
    <div className="app">
      <div className="sidebar">
        <h2>Truck Weather Router</h2>
        <TripForm onSubmit={planTrip} loading={loading} />
        {error && <div className="error">{error}</div>}
        {!plan && !loading && (
          <p className="intro">
            Enter a trip and load. The app finds 3 truck routes, checks the forecast at every checkpoint for the time
            the truck gets there, and recommends the safest one.
          </p>
        )}
        <RouteCards plan={plan} partial={partial} loading={loading} selected={selected} onSelect={selectRoute} />
      </div>

      <div className="map-container">
        <RouteMap
          plan={plan}
          selected={selected}
          onSelect={selectRoute}
          onCheckpointClick={selectCheckpoint}
          heat={heat}
          hour={hour}
          showHeat={showHeat}
          truckRoute={selectedRoute}
          truckTime={truckTime}
          checkpoint={selectedRoute && selectedRoute.checkpoints[cpIndex]}
        />
        {selectedRoute && (
          <CheckpointPanel
            route={selectedRoute}
            index={cpIndex}
            recommended={!partial && selectedRoute.id === plan.recommended}
            onStep={(d) => selectCheckpoint(selectedRoute.id, cpIndex + d)}
          />
        )}
        <Legend />
        {loading && <div className="map-loading">{partial ? 'Finding alternative routes...' : 'Finding routes...'}</div>}
        {selectedRoute && (
          <TimeSlider
            heat={heat}
            error={heatErrors[heatKey(selectedRoute, corridor)]}
            onRetry={() => loadHeatmap(lastForm.current, selectedRoute, requestId.current, corridor)}
            corridor={corridor}
            setCorridor={setCorridor}
            routeLabel={selectedRoute.label}
            hour={hour}
            setHour={setHour}
            playing={playing}
            setPlaying={setPlaying}
            onTogglePlay={togglePlay}
            arrived={arrived}
            showHeat={showHeat}
            setShowHeat={setShowHeat}
          />
        )}
      </div>
    </div>
  )
}

export default App
