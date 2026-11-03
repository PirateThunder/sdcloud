import katex from 'katex'

import { cn } from '@/fsd/shared/lib/utils'

export function MathFormula({
  formula,
  display = true,
  className,
}: {
  formula: string
  display?: boolean
  className?: string
}) {
  const html = katex.renderToString(formula, {
    displayMode: display,
    output: 'html',
    throwOnError: false,
    strict: 'warn',
  })
  return (
    <div
      className={cn('math-formula min-w-0 max-w-full', display && 'math-display', className)}
      // biome-ignore lint/security/noDangerouslySetInnerHtml: KaTeX output is generated from the validated canonical AST
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}
