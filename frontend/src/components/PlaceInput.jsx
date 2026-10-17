import { useEffect, useRef, useState } from 'react'
import { API_URL } from '../constants'

// text field with suggestions from /api/places/. value = { text, place }, place is the
// picked suggestion ({ name, lat, lon }) or null if the user only typed.
// typed text still works (the backend picks the best match), but typos like "Chenai"
// used to land in belgium, so picking from the list is the safe way
function PlaceInput({ value, onChange }) {
  const [suggestions, setSuggestions] = useState([])
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const latestQuery = useRef('')

  // search 250 ms after the user stops typing, not on every key
  useEffect(() => {
    const q = value.text.trim()
    if (value.place || q.length < 2) {
      setSuggestions([])
      return
    }
    latestQuery.current = q
    const timer = setTimeout(() => {
      fetch(API_URL + '/api/places/?q=' + encodeURIComponent(q))
        .then((r) => r.json())
        .then((data) => {
          if (latestQuery.current !== q) return // user kept typing, this answer is old
          setSuggestions(data.places || [])
          setActive(0)
        })
        .catch(() => setSuggestions([]))
    }, 250)
    return () => clearTimeout(timer)
  }, [value.text, value.place])

  function pick(p) {
    onChange({ text: p.name, place: p })
    setOpen(false)
  }

  function onKeyDown(e) {
    if (!open || suggestions.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((active + 1) % suggestions.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((active - 1 + suggestions.length) % suggestions.length)
    } else if (e.key === 'Enter') {
      e.preventDefault() // pick the suggestion, don't submit the form yet
      pick(suggestions[active])
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  return (
    <div className="place-input">
      <input
        value={value.text}
        onChange={(e) => {
          onChange({ text: e.target.value, place: null })
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={onKeyDown}
        required
      />
      {open && suggestions.length > 0 && (
        <ul className="suggestions">
          {suggestions.map((p, i) => (
            <li
              key={p.name + p.lat}
              className={i === active ? 'active' : ''}
              // mousedown, not click: click comes after the input's blur closed the list
              onMouseDown={() => pick(p)}
              onMouseEnter={() => setActive(i)}
            >
              {p.name} <span>{p.type}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default PlaceInput
