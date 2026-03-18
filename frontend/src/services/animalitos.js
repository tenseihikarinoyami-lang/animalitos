// Animalitos mapping - shared between frontend and backend
export const ANIMALITOS_MAP = {
  0: 'Delfín', 1: 'Carnero', 2: 'Toro', 3: 'Ciempiés', 4: 'Alacrán',
  5: 'León', 6: 'Rana', 7: 'Perico', 8: 'Ratón', 9: 'Águila',
  10: 'Tigre', 11: 'Gato', 12: 'Caballo', 13: 'Mono', 14: 'Paloma',
  15: 'Zorro', 16: 'Oso', 17: 'Pavo', 18: 'Burro', 19: 'Chivo',
  20: 'Cochino', 21: 'Gallo', 22: 'Camello', 23: 'Cebra', 24: 'Iguana',
  25: 'Gallina', 26: 'Vaca', 27: 'Perro', 28: 'Zamuro', 29: 'Elefante',
  30: 'Caimán', 31: 'Lapa', 32: 'Ardilla', 33: 'Pescado', 34: 'Venado',
  35: 'Jirafa', 36: 'Culebra', 37: 'Shark', 38: 'Cangrejo', 39: 'Pavo Real',
  40: 'Oso Hormiguero', 41: 'Halcón', 42: 'Búho', 43: 'Puercoespín', 44: 'Loro',
  45: 'Serpiente', 46: 'Erizo', 47: 'Cordero', 48: 'Torito', 49: 'Indio',
  50: 'Gusano', 51: 'Flamenco', 52: 'Cocodrilo', 53: 'Mico', 54: 'Lechuza',
  55: 'Avispa', 56: 'Mula', 57: 'Pavito', 58: 'Hipopótamo', 59: 'Gemelos',
  60: 'Escorpión', 61: 'Pingüino', 62: 'Cachicamo', 63: 'Cebra Rayada',
  64: 'Ciervo', 65: 'Cotorra', 66: 'Lobo', 67: 'Puerquito', 68: 'Orca',
  69: 'Adán', 70: 'Eva', 71: 'Guacamaya', 72: 'Pulpo', 73: 'Conejo',
  74: 'Búfalo', 75: 'Cucarachita', 76: 'Pacheco', 77: 'Piña', 78: 'Mango',
  79: 'Fresa', 80: 'Coco', 81: 'Cereza', 82: 'Manzana', 83: 'Pera',
  84: 'Melón', 85: 'Uva', 86: 'Naranja', 87: 'Limón', 88: 'Patilla',
  89: 'Guayaba', 90: 'Cambio', 91: 'Agua', 92: 'Fuego', 93: 'Aire',
  94: 'Paujil', 95: 'Viejo', 96: 'Niña', 97: 'Espada', 98: 'Anillo',
  99: 'Beso', 100: 'Muerto'
}

export function getAnimalName(number) {
  return ANIMALITOS_MAP[number % 101] || 'Desconocido'
}

export function getNumberFromAnimal(animalName) {
  for (const [num, name] of Object.entries(ANIMALITOS_MAP)) {
    if (name.toLowerCase() === animalName.toLowerCase()) {
      return parseInt(num)
    }
  }
  return null
}
