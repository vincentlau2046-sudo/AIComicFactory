import type { ResolveContext } from './types'

// ─── Template Expression Parser ──────────────────────────────

const TEMPLATE_RE = /\$\{([^}]+)\}/g

/**
 * Resolve a template string like "${params.prompt}, output: ${steps.gen_front.front_image}"
 * into a concrete value.
 *
 * Expression syntax:
 *   ${params.key}            → PipelineInputs[key]
 *   ${steps.stepId.name}     → StepOutput.named[name]
 *   ${steps.stepId.$all[i]}  → StepOutput.outputs[i]
 *   ${outputs[i].localPath}  → workaround → same as outputs[i]
 *   ${env.VAR_NAME}          → process.env[VAR_NAME]
 *   ${iter.index}            → ResolveContext.iter.index
 *   ${iter.count}            → ResolveContext.iter.count
 *   ${literal}               → plain string literal
 */
export function resolveTemplate(
  template: string | number | boolean | null,
  ctx: ResolveContext
): string | number | boolean | null {
  if (template === null || typeof template === 'boolean') return template
  if (typeof template === 'number') return template

  // Pure expression (no surrounding text) — coerce to the original type
  const trimmed = template.trim()
  const pureMatch = trimmed.match(/^\$\{([^}]+)\}$/)
  if (pureMatch) {
    const resolved = resolveExpression(pureMatch[1], ctx)
    if (typeof resolved === 'string' || typeof resolved === 'number' || typeof resolved === 'boolean' || resolved === null) {
      return resolved
    }
    return resolved != null ? String(resolved) : null
  }

  // Template with text — string interpolation
  return template.replace(TEMPLATE_RE, (_, expr: string) => {
    const resolved = resolveExpression(expr.trim(), ctx)
    return resolved == null ? '' : String(resolved)
  })
}

/**
 * Resolve a pipeline of function calls or property accesses.
 * Supports: params.x, steps.y.z, env.X, iter.index, iter.count
 */
function resolveExpression(expr: string, ctx: ResolveContext): unknown {
  // Support simple arithmetic: ${params.seed + 1}, ${params.seed - 2}, ${params.seed * 3}
  const arithMatch = expr.match(/^(\$\{[^}]+\}|[a-zA-Z_][\w.\[\]]*)\s*([+\-*/])\s*(\d+)$/)
  if (arithMatch) {
    const baseExpr = arithMatch[1].replace(/^\$\{|\}$/g, '')
    const op = arithMatch[2]
    const operand = parseInt(arithMatch[3], 10)
    const base = resolveExpression(baseExpr, ctx)
    if (typeof base === 'number') {
      switch (op) {
        case '+': return base + operand
        case '-': return base - operand
        case '*': return base * operand
        case '/': return Math.floor(base / operand)
      }
    }
    return base // Can't do arithmetic on non-number, return as-is
  }

  const parts = expr.split('.')

  // Short-circuit for simple paths
  if (parts[0] === 'params') {
    return followPath(ctx.inputs, parts.slice(1))
  }
  if (parts[0] === 'env') {
    // Prefer ctx.env over process.env for testability
    const envSource = ctx.env ?? (process.env as Record<string, string | undefined>)
    return followPath(envSource, parts.slice(1))
  }
  if (parts[0] === 'iter') {
    return ctx.iter
      ? followPath(ctx.iter as unknown as Record<string, unknown>, parts.slice(1))
      : undefined
  }
  if (parts[0] === 'steps') {
    return resolveStepExpression(parts.slice(1), ctx)
  }
  if (parts[0] === 'outputs') {
    // ${outputs[i].localPath} — used by step executor to reference own output
    const idxPart = parts[1]?.replace(/[\[\]]/g, '')
    const idx = parseInt(idxPart, 10)
    if (!isNaN(idx) && parts[2] === 'localPath') {
      // This is resolved at step executor level after execution
      // For template resolution, return a placeholder marker
      return `__MARKER_OUTPUTS_${idx}__`
    }
  }
  // Unknown — return as-is
  return undefined
}

function resolveStepExpression(parts: string[], ctx: ResolveContext): unknown {
  if (parts.length < 1) return undefined

  const stepId = parts[0]
  const step = ctx.steps.get(stepId)
  if (!step) return undefined

  // No more parts — return the first output
  if (parts.length === 1) {
    return step.outputs[0] ?? undefined
  }

  const field = parts[1]

  // Handle $all[i] or outputs[i] accessor
  const arrayMatch = field.match(/^(?:outputs|\$all)\[(\d+)\]$/)
  if (arrayMatch) {
    const idx = parseInt(arrayMatch[1], 10)
    if (idx < step.outputs.length) {
      return step.outputs[idx]
    }
    return undefined
  }

  // Named output
  const named = step.named[field]
  if (named !== undefined) return named

  // Fallback: direct index
  const idx = parseInt(field, 10)
  if (!isNaN(idx) && idx < step.outputs.length) {
    return step.outputs[idx]
  }

  return undefined
}

function followPath(
  obj: Record<string, unknown> | undefined | null,
  path: string[]
): unknown {
  let current: unknown = obj
  for (const key of path) {
    if (current == null || typeof current !== 'object') return undefined

    // Support bracket notation: key[0] → access index 0 of array
    const bracketMatch = key.match(/^(.+?)\[(\d+)\]$/)
    if (bracketMatch) {
      const [, baseKey, idxStr] = bracketMatch
      const idx = parseInt(idxStr, 10)
      const base = (current as Record<string, unknown>)[baseKey]
      if (Array.isArray(base) && idx < base.length) {
        current = base[idx]
      } else {
        return undefined
      }
    } else {
      current = (current as Record<string, unknown>)[key]
    }
  }
  return current
}

/**
 * Resolve an entire input map. Returns a new object with templates resolved.
 */
export function resolveInputs(
  raw: Record<string, string | number | boolean | null>,
  ctx: ResolveContext
): Record<string, string | number | boolean | null> {
  const result: Record<string, string | number | boolean | null> = {}
  for (const [key, value] of Object.entries(raw)) {
    result[key] = resolveTemplate(value, ctx)
  }
  return result
}

/**
 * Resolve output path templates and return the concrete named paths.
 * Replaces __MARKER_OUTPUTS_N__ placeholders with actual output file paths.
 */
export function resolveOutputPaths(
  outputDefs: Record<string, string>,
  outputPaths: string[]
): Record<string, string> {
  const result: Record<string, string> = {}
  for (const [name, template] of Object.entries(outputDefs)) {
    // Replace __MARKER_OUTPUTS_N__ with actual paths
    let resolved = template
    resolved = resolved.replace(/__MARKER_OUTPUTS_(\d+)__/g, (_, idx: string) => {
      const i = parseInt(idx, 10)
      return i < outputPaths.length ? outputPaths[i] : ''
    })
    // If still has template markers, resolve them too
    if (resolved.includes('${')) {
      // Simple case: just use the first output as fallback
      resolved = outputPaths[0] ?? ''
    }
    result[name] = resolved
  }
  return result
}