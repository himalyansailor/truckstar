export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// esri tiles: fast (~0.05s a tile vs ~1s for tomtom), english labels, no key.
// tried tomtom tiles with view=IN for india's official borders but the map was too slow
export const TILES = {
  url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',
  attribution: 'Tiles &copy; <a href="https://www.esri.com">Esri</a>',
}

export const RISK_COLORS = ['#3fb950', '#e3c11b', '#f0883e', '#e5534b', '#8957e5']
export const RISK_NAMES = ['Low', 'Moderate', 'High', 'Severe', 'No Travel']

// times are in the viewer's timezone (the departure field is too), with the zone shown so
// a Chennai trip planned from Chicago doesn't look wrong: "Sat 7:30 PM CDT"
export function formatTime(iso) {
  return new Date(iso).toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' })
}

// "CDT", "GMT+5:30" ... for the departure label
export const TIMEZONE = new Intl.DateTimeFormat([], { timeZoneName: 'short' })
  .formatToParts(new Date())
  .find((p) => p.type === 'timeZoneName').value

// 16.47 -> "16h 28m"
export function formatDuration(hours) {
  const total = Math.round(hours * 60)
  return Math.floor(total / 60) + 'h ' + (total % 60) + 'm'
}
