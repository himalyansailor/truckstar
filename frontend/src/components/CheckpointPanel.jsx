import { RISK_COLORS, RISK_NAMES, formatDuration, formatTime } from '../constants'

// box on the map: summary of the selected route + the checkpoint the truck is at.
// the checkpoint follows the slider, the arrows jump to the previous / next one
function CheckpointPanel({ route, index, recommended, onStep }) {
  const s = route.summary
  const c = route.checkpoints[index]
  const last = route.checkpoints.length - 1

  return (
    <div className="cp-panel">
      <div className="cp-route">
        <b>{route.label}</b>
        {recommended && <span className="badge green">Recommended</span>}
        <span className="badge" style={{ background: RISK_COLORS[RISK_NAMES.indexOf(s.worst)] }}>
          worst: {s.worst}
        </span>
        <div className="small">
          {route.distance_mi} mi · {formatDuration(route.duration_hr)} ·
          arrives {formatTime(route.arrive_at)}
          <br />
          Severe {s.severe_miles} mi · High {s.high_miles} mi · avg risk {s.avg_risk}
          {s.no_travel_miles > 0 && <b style={{ color: RISK_COLORS[4] }}> · No Travel {s.no_travel_miles} mi</b>}
        </div>
      </div>

      <div className="cp-head">
        <button onClick={() => onStep(-1)} disabled={index === 0} title="Previous checkpoint">
          ‹
        </button>
        <span>
          Checkpoint {index + 1} of {last + 1} · mile {Math.round(c.mile)}
        </span>
        <button onClick={() => onStep(1)} disabled={index === last} title="Next checkpoint">
          ›
        </button>
      </div>

      <div className="cp-row">
        <span>ETA</span>
        <b>{formatTime(c.eta)}</b>
      </div>
      <div className="cp-row">
        <span>Risk</span>
        <b style={{ color: RISK_COLORS[c.risk] }}>{c.risk_label}</b>
      </div>
      <div className="cp-row">
        <span>Wind</span>
        <span>
          {c.wind_mph} mph (gusts {c.gust_mph})
        </span>
      </div>
      <div className="cp-row">
        <span>Rain</span>
        <span>{c.rain_in} in/hr</span>
      </div>
      <div className="cp-row">
        <span>Snow</span>
        <span>{c.snow_in} in/hr</span>
      </div>
      {c.reasons.length > 0 && <div className="small">Because: {c.reasons.join(', ')}</div>}
    </div>
  )
}

export default CheckpointPanel
