export const PRIMARY_LOTTERIES = [
  'Lotto Activo',
  'La Granjita',
  'Lotto Activo Internacional',
]

const SOURCE_BASE_URL = 'https://loteriadehoy.com'
const FALLBACK_ANIMAL_ICON = `${SOURCE_BASE_URL}/dist/animals_img/Pescado_2.webp`
const FALLBACK_LOTTERY_ICON = `${SOURCE_BASE_URL}/dist/files_img/side-Lotto_Activo.webp`

const LOTTERY_ICON_MAP = {
  'Lotto Activo': `${SOURCE_BASE_URL}/dist/files_img/side-Lotto_Activo.webp`,
  'La Granjita': `${SOURCE_BASE_URL}/dist/files_img/side-La_Granjita.webp`,
  'Lotto Activo Internacional': `${SOURCE_BASE_URL}/dist/files_img/side-Lotto_Activo_RD_Int.webp`,
}

const LOTTERY_ANIMAL_SUFFIX_MAP = {
  'Lotto Activo': '2',
  'La Granjita': '2',
  'Lotto Activo Internacional': '21',
}

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

export function countdownLabel(minutes) {
  if (minutes === null || minutes === undefined) return 'Sin siguiente sorteo'
  if (minutes < 60) return `${minutes} min`
  const hours = Math.floor(minutes / 60)
  const remainder = minutes % 60
  return `${hours}h ${remainder}m`
}

function toTitleCaseToken(value) {
  return (value || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-zA-Z0-9]+/g, ' ')
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map((token) => token.charAt(0).toUpperCase() + token.slice(1).toLowerCase())
    .join('_')
}

export function lotteryIconUrl(lotteryName) {
  return LOTTERY_ICON_MAP[lotteryName] || FALLBACK_LOTTERY_ICON
}

export function animalIconUrl(animalName, lotteryName = 'Lotto Activo') {
  const normalizedAnimal = toTitleCaseToken(animalName)
  if (!normalizedAnimal) return FALLBACK_ANIMAL_ICON
  const suffix = LOTTERY_ANIMAL_SUFFIX_MAP[lotteryName] || '2'
  return `${SOURCE_BASE_URL}/dist/animals_img/${normalizedAnimal}_${suffix}.webp`
}

export function handleIconError(event, type = 'animal') {
  if (!event?.target) return
  const fallback = type === 'lottery' ? FALLBACK_LOTTERY_ICON : FALLBACK_ANIMAL_ICON
  if (event.target.dataset?.fallbackApplied === 'true') return
  event.target.dataset.fallbackApplied = 'true'
  event.target.src = fallback
}
