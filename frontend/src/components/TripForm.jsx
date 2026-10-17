import { useState } from 'react'
import PlaceInput from './PlaceInput'

function nextHour() {
  const d = new Date(Date.now() + 60 * 60 * 1000)
  d.setMinutes(0, 0, 0)
  // datetime-local input needs local time without the Z, toISOString is UTC so shift it
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}

// one click trips. denver -> salt lake city is I-80 through the wyoming wind corridor
// (where the heavy load rules matter), the other two are mountain / monsoon routes in india
const EXAMPLES = [
  ['Denver, Colorado', 'Salt Lake City, Utah'],
  ['Chennai, Tamil Nadu', 'Kanyakumari, Tamil Nadu'],
  ['Shimla, Himachal Pradesh', 'Leh, Ladakh'],
]

function TripForm({ onSubmit, loading }) {
  const [origin, setOrigin] = useState({ text: EXAMPLES[0][0], place: null })
  const [destination, setDestination] = useState({ text: EXAMPLES[0][1], place: null })
  const [departTime, setDepartTime] = useState(nextHour())
  const [weight, setWeight] = useState(38000)
  const [interval, setInterval] = useState(25)

  function submit(from, to) {
    onSubmit({
      // the picked suggestion (exact coordinates) or just the text
      origin: from.place || from.text,
      destination: to.place || to.text,
      depart_at: new Date(departTime).toISOString(),
      weight: Number(weight),
      interval_mi: Number(interval),
    })
  }

  function handleSubmit(e) {
    e.preventDefault()
    submit(origin, destination)
  }

  // fills in the trip and plans it straight away (keeps departure, load, interval)
  function tryExample([from, to]) {
    const o = { text: from, place: null }
    const d = { text: to, place: null }
    setOrigin(o)
    setDestination(d)
    submit(o, d)
  }

  return (
    <form onSubmit={handleSubmit}>
      <label>From</label>
      <PlaceInput value={origin} onChange={setOrigin} />

      <label>To</label>
      <PlaceInput value={destination} onChange={setDestination} />

      <label>Departure</label>
      <input type="datetime-local" value={departTime} onChange={(e) => setDepartTime(e.target.value)} required />

      <div style={{ display: 'flex', gap: 10 }}>
        <div style={{ flex: 1 }}>
          <label>Load (lb)</label>
          <input type="number" value={weight} min="1000" onChange={(e) => setWeight(e.target.value)} required />
        </div>
        <div style={{ flex: 1 }}>
          <label>Check weather every</label>
          <select value={interval} onChange={(e) => setInterval(e.target.value)}>
            <option value="10">10 miles</option>
            <option value="25">25 miles</option>
            <option value="50">50 miles</option>
          </select>
        </div>
      </div>

      <button type="submit" disabled={loading}>
        {loading ? 'Loading...' : 'Find Safest Route'}
      </button>
      <div className="examples">
        Try:{' '}
        {EXAMPLES.map((ex) => (
          <button key={ex[0]} type="button" disabled={loading} onClick={() => tryExample(ex)}>
            {ex[0].split(',')[0]} → {ex[1].split(',')[0]}
          </button>
        ))}
      </div>
    </form>
  )
}

export default TripForm
