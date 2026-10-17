import { useState } from 'react'
import { RISK_COLORS, RISK_NAMES } from '../constants'

// same thresholds as get_risk() in the backend / the table in the requirement.
// a range includes its lower number, e.g. 0.25 in/hr rain is High
const RANGES = [
  ['< 25', '< 0.10', '< 0.5'],
  ['25–34', '0.10–0.25', '0.5–1'],
  ['35–44', '0.25–0.50', '1–2'],
  ['45–54', '0.50–1.00', '2–3'],
  ['≥ 55', '> 1.00', '> 3'],
]

function Legend() {
  const [open, setOpen] = useState(true)

  return (
    <div className="legend">
      <div className="legend-head" onClick={() => setOpen(!open)}>
        <b>Risk levels</b> <span>{open ? '▾' : '▸'}</span>
      </div>
      {open ? (
        <>
          <table>
            <thead>
              <tr>
                <th></th>
                <th>Wind mph</th>
                <th>Rain in/hr</th>
                <th>Snow in/hr</th>
              </tr>
            </thead>
            <tbody>
              {RISK_NAMES.map((name, i) => (
                <tr key={name}>
                  <td>
                    <i style={{ background: RISK_COLORS[i] }}></i>
                    {name}
                  </td>
                  <td>{RANGES[i][0]}</td>
                  <td>{RANGES[i][1]}</td>
                  <td>{RANGES[i][2]}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="legend-note">
            Heavy loads: 45–54 mph &amp; &gt;30,000 lb → No Travel, 35–44 mph &amp; &gt;40,000 lb → Severe.
            <br />
            Checkpoint = worst of wind / rain / snow. Heatmap = risk at the slider time.
            <br />
            Route line colour = risk on that stretch (like traffic on google maps). Dark outline = selected route, faded = other options.
          </div>
        </>
      ) : (
        <div className="legend-dots">
          {RISK_NAMES.map((name, i) => (
            <span key={name}>
              <i style={{ background: RISK_COLORS[i] }}></i>
              {name}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

export default Legend
