import { formatTime } from '../constants'

// what each corridor width means, shown under the slider so the trade-off is clear.
// point counts measured on 420-680 mi routes
const CORRIDOR_NOTES = {
  1: 'Shows weather up to ~15 mi either side of the road (~90-140 weather lookups per route). Fewer calls to the free weather API, but storms further from the road are not shown.',
  2: 'Shows weather up to ~30 mi either side (~66% more lookups, ~145-230 per route). Wider view, but the free weather API has a per-minute limit: planning a few new trips quickly can hit it, then the heatmap shows Retry. Risk levels and routes are not affected either way.',
}

// the heatmap width select (±15 / ±30 mi) with the note on what each costs
function CorridorPicker({ corridor, setCorridor }) {
  return (
    <div className="corridor">
      <label>
        Heatmap corridor{' '}
        <select value={corridor} onChange={(e) => setCorridor(Number(e.target.value))}>
          <option value={1}>±15 mi (fewer API calls)</option>
          <option value={2}>±30 mi (wider, more API calls)</option>
        </select>
      </label>
      <div className="corridor-note">{CORRIDOR_NOTES[corridor]}</div>
    </div>
  )
}

// box at the bottom of the map: 0-48h slider, play button, heatmap on / off and corridor width.
// while the heatmap loads it says so; if it failed, the error and a Retry button
function TimeSlider({
  heat,
  error,
  onRetry,
  routeLabel,
  hour,
  setHour,
  playing,
  setPlaying,
  onTogglePlay,
  arrived,
  showHeat,
  setShowHeat,
  corridor,
  setCorridor,
}) {
  if (!heat && error) {
    return (
      <div className="slider-box">
        <div className="slider-row">
          <span style={{ flex: 1 }}>
            Couldn't load the weather heatmap for {routeLabel} ({error}). Routes and risk are fine.
          </span>
          <button className="retry" onClick={onRetry}>
            Retry
          </button>
        </div>
        <CorridorPicker corridor={corridor} setCorridor={setCorridor} />
      </div>
    )
  }

  if (!heat) {
    return (
      <div className="slider-box">
        <div className="slider-row">
          <span>Loading weather heatmap for {routeLabel}...</span>
        </div>
        <CorridorPicker corridor={corridor} setCorridor={setCorridor} />
      </div>
    )
  }

  const sliderTime = formatTime(new Date(heat.start).getTime() + hour * 3600 * 1000)

  return (
    <div className="slider-box">
      <div className="slider-row">
        <button className="play" onClick={onTogglePlay} title={playing ? 'Pause' : arrived ? 'Play again' : 'Play'}>
          {playing ? '❚❚' : arrived ? '↺' : '▶'}
        </button>
        <input
          type="range"
          min="0"
          max="48"
          step="0.1"
          value={hour}
          onChange={(e) => {
            setPlaying(false)
            setHour(Number(e.target.value))
          }}
          style={{ flex: 1 }}
        />
        <span style={{ width: 215 }}>
          <b>+{Math.floor(hour)}h</b> {sliderTime}
          {arrived && <span className="arrived"> · arrived</span>}
        </span>
        <label>
          <input type="checkbox" checked={showHeat} onChange={(e) => setShowHeat(e.target.checked)} /> Heatmap
        </label>
      </div>
      <CorridorPicker corridor={corridor} setCorridor={setCorridor} />
    </div>
  )
}

export default TimeSlider
