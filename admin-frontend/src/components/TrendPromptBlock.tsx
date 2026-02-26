import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'

export interface TrendPromptBlockProps {
  tag: string
  title: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
  rows?: number
  error?: boolean
  required?: boolean
  hint?: string
  id?: string
  /** Дополнительный контент под полем (например, радиокнопки для стиля) */
  children?: React.ReactNode
}

export function TrendPromptBlock({
  tag,
  title,
  value,
  onChange,
  placeholder = '',
  rows = 4,
  error = false,
  required = false,
  hint,
  id: idProp,
  children,
}: TrendPromptBlockProps) {
  const id = idProp ?? `trend-prompt-${tag.toLowerCase().replace(/\s+/g, '-')}`
  const errorId = error ? `${id}-error` : undefined
  return (
    <div className="space-y-4 rounded-lg border border-border/50 bg-muted/30 p-4">
      <h3 className="text-sm font-medium">
        <span className="font-mono text-muted-foreground">[{tag}]</span> {title}
        {required && ' *'}
      </h3>
      <div className="grid gap-2">
        <Label htmlFor={id} className="sr-only">
          {title}
        </Label>
        <Textarea
          id={id}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          rows={rows}
          placeholder={placeholder}
          className={cn(
            'font-mono text-sm',
            error && 'border-destructive focus-visible:ring-destructive'
          )}
          aria-required={required}
          aria-invalid={error}
          aria-describedby={error ? errorId : hint ? `${id}-hint` : undefined}
        />
        {children}
        {error && (
          <p id={errorId} className="text-xs text-destructive">
            Поле не должно быть пустым.
          </p>
        )}
        {hint && (
          <p id={`${id}-hint`} className="text-xs text-muted-foreground">
            {hint}
          </p>
        )}
      </div>
    </div>
  )
}
