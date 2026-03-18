export const PRIMARY_LOTTERIES = [
  'Lotto Activo',
  'La Granjita',
  'Lotto Activo Internacional',
]

export function formatDateTime(value) {
  if (!value) return 'Sin fecha'
  return new Intl.DateTimeFormat('es-VE', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

export function formatShortDate(value) {
  if (!value) return '--'
  return new Intl.DateTimeFormat('es-VE', {
    month: 'short',
    day: '2-digit',
  }).format(new Date(value))
}

export function formatPercent(value) {
  return `${Math.round((value || 0) * 100)}%`
}

export function formatDrawTime(value) {
  if (!value) return '--:--'
  if (value.includes(':') && value.length <= 5) return value
  return new Intl.DateTimeFormat('es-VE', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

export function emojiForAnimal(animalName) {
  const normalized = (animalName || '').toLowerCase()
  if (normalized.includes('gato')) return '🐱'
  if (normalized.includes('perro')) return '🐶'
  if (normalized.includes('pescado')) return '🐟'
  if (normalized.includes('tigre')) return '🐯'
  if (normalized.includes('leon')) return '🦁'
  if (normalized.includes('rana')) return '🐸'
  if (normalized.includes('mono')) return '🐒'
  if (normalized.includes('ardilla')) return '🐿️'
  if (normalized.includes('toro')) return '🐂'
  if (normalized.includes('aguila')) return '🦅'
  if (normalized.includes('gallo')) return '🐓'
  if (normalized.includes('ballena')) return '🐋'
  return '🎯'
}

export function countdownLabel(minutes) {
  if (minutes === null || minutes === undefined) return 'Sin siguiente sorteo'
  if (minutes < 60) return `${minutes} min`
  const hours = Math.floor(minutes / 60)
  const remainder = minutes % 60
  return `${hours}h ${remainder}m`
}
