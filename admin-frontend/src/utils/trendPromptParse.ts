/**
 * Парсинг и сборка полного промпта тренда из трёх блоков [SCENE], [STYLE], [AVOID].
 * Маркеры должны быть в начале строки (после trim). Порядок блоков произвольный.
 */

const MARKERS = ['[SCENE]', '[STYLE]', '[AVOID]'] as const
type Marker = (typeof MARKERS)[number]

export interface ParsedFullTrendPrompt {
  scene: string
  style: string
  avoid: string
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
 * Разбирает текст с маркерами [SCENE], [STYLE], [AVOID] на три блока.
 * Маркеры только в начале строки. При отсутствии блока возвращается пустая строка.
 */
export function parseFullTrendPrompt(text: string): ParsedFullTrendPrompt {
  const lines = text.split(/\r?\n/)
  const scene = extractBlock(lines, '[SCENE]')
  const style = extractBlock(lines, '[STYLE]')
  const avoid = extractBlock(lines, '[AVOID]')
  const styleParsedAsJson = style.length > 0 && isStyleValidJson(style)
  return { scene, style, avoid, styleParsedAsJson }
}

/**
 * Собирает три блока в один текст с заголовками секций для копирования или повторного разбора.
 */
export function buildFullTrendPrompt(scene: string, style: string, avoid: string): string {
  const parts: string[] = []
  parts.push('[SCENE]', (scene || '').trim(), '')
  parts.push('[STYLE]', (style || '').trim(), '')
  parts.push('[AVOID]', (avoid || '').trim())
  return parts.join('\n')
}
