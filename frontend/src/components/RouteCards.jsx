import { RISK_COLORS, RISK_NAMES, formatDuration, formatTime } from '../constants'

// grey placeholder card with a shimmer while a route is still loading
function SkeletonCard() {
  return (
    <div className="route-card skeleton">
      <div className="sk-line" style={{ width: '45%' }}></div>
      <div className="sk-line" style={{ width: '80%' }}></div>
      <div className="sk-bar"></div>
      <div className="sk-line" style={{ width: '60%' }}></div>
    </div>
  )
}

// one route in the sidebar: distance, time, arrival, a bar of miles per risk level, and the
// recommended badge + reason. click selects the route
function RouteCard({ r, plan, partial, selected, onSelect }) {
  const s = r.summary
  const totalMiles = r.checkpoints[r.checkpoints.length - 1].mile
  // no "recommended" until all 3 routes are in, can't compare yet
  const recommended = !partial && r.id === plan.recommended
  return (
    <div className={r.id === selected ? 'route-card selected' : 'route-card'} onClick={() => onSelect(r.id)}>
      <div>
        <b>{r.label}</b>
        {recommended && <span className="badge green">Recommended</span>}
        <span className="badge" style={{ background: RISK_COLORS[RISK_NAMES.indexOf(s.worst)] }}>
          {s.worst}
        </span>
      </div>
      <div className="route-info">
        {r.distance_mi} mi | {formatDuration(r.duration_hr)} | arrives{' '}
        {formatTime(r.arrive_at)}
      </div>

      {/* bar showing how many miles in each risk level */}
      <div className="risk-bar">
        {RISK_NAMES.map((name, i) => (
          <div
            key={name}
            style={{ width: (s.miles_by_level[name] / totalMiles) * 100 + '%', background: RISK_COLORS[i] }}
          ></div>
        ))}
      </div>

      <div className="small">
        Severe: {s.severe_miles} mi, High: {s.high_miles} mi, Avg risk: {s.avg_risk}
        {s.no_travel_miles > 0 && <b style={{ color: RISK_COLORS[4] }}> NO TRAVEL: {s.no_travel_miles} mi</b>}
      </div>
      {recommended && <div className="small" style={{ color: 'green' }}>{plan.why}</div>}
    </div>
  )
}

// the sidebar list: which places the plan used, a card per route, and grey skeleton cards
// for the routes still loading
function RouteCards({ plan, partial, loading, selected, onSelect }) {
  const routes = plan ? plan.routes : []
  const skeletons = loading ? Math.max(0, 3 - routes.length) : 0

  return (
    <>
      {/* the places the plan actually used, so a wrong match is obvious */}
      {plan && (
        <div className="trip-places">
          {plan.origin.name} → {plan.destination.name}
        </div>
      )}
      {routes.map((r) => (
        <RouteCard key={r.id} r={r} plan={plan} partial={partial} selected={selected} onSelect={onSelect} />
      ))}
      {skeletons > 0 && (
        <div className="loading-text">
          {routes.length ? 'Finding alternative routes...' : 'Finding routes and checking the weather...'}
        </div>
      )}
      {Array.from({ length: skeletons }, (_, i) => (
        <SkeletonCard key={'sk' + i} />
      ))}
    </>
  )
}

export default RouteCards
