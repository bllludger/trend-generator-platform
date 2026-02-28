/**
 * Парсинг и сборка полного промпта тренда из четырёх блоков [], [STYLE], [AVOID], [COMPOSITION].
 * Маркер сцены — пустые скобки [] (чтобы не путать модель). Остальные маркеры в начале строки.
 */

const MARKERS = ['[]', '[STYLE]', '[AVOID]', '[COMPOSITION]'] as const
type Marker = (typeof MARKERS)[number]

export interface ParsedFullTrendPrompt {
  scene: string
  style: string
  avoid: string
  composition: string
  styleParsedAsJson: boolean
}

function extractBlock(lines: string[], marker: Marker): string {
  const idx = lines.findIndex((line) => line.trim() === marker)
  if (idx === -1) return ''
  const start = idx + 1
  let end = lines.length
  for (let i = start; i < lines.length; i++) {
    const trimmed = lines[i].trim()
    if (MARKERS.includes(trimmed as Marker)) {
      end = i
      break
    }
  }
  const slice = lines.slice(start, end)
  return slice.join('\n').trim()
}

function isStyleValidJson(style: string): boolean {
  const s = style.trim()
  if (!s.startsWith('{') || !s.endsWith('}')) return false
  try {
    const parsed = JSON.parse(s)
    return typeof parsed === 'object' && parsed !== null
  } catch {
    return false
  }
}

/**
 * Разбирает текст с маркерами [], [STYLE], [AVOID], [COMPOSITION] на четыре блока.
 * Маркер сцены — []. Остальные маркеры в начале строки. При отсутствии блока — пустая строка.
 */
export function parseFullTrendPrompt(text: string): ParsedFullTrendPrompt {
  const lines = text.split(/\r?\n/)
  const scene = extractBlock(lines, '[]')
  const style = extractBlock(lines, '[STYLE]')
  const avoid = extractBlock(lines, '[AVOID]')
  const composition = extractBlock(lines, '[COMPOSITION]')
  const styleParsedAsJson = style.length > 0 && isStyleValidJson(style)
  return { scene, style, avoid, composition, styleParsedAsJson }
}

/**
 * Собирает в текст только блоки с непустым содержимым; маркер сцены — [] (пустые скобки).
 * Стиль "{}" считается пустым и не выводится.
 */
export function buildFullTrendPrompt(scene: string, style: string, avoid: string, composition: string): string {
  const sections: string[] = []
  const s = (scene || '').trim()
  const st = (style || '').trim()
  const a = (avoid || '').trim()
  const c = (composition || '').trim()
  const hasStyle = st && st !== '{}'
  if (s) sections.push('[]\n' + s)
  if (hasStyle) sections.push('[STYLE]\n' + st)
  if (a) sections.push('[AVOID]\n' + a)
  if (c) sections.push('[COMPOSITION]\n' + c)
  return sections.join('\n\n')
}
