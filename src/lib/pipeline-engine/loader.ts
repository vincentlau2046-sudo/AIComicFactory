import fs from 'node:fs'
import path from 'node:path'
import * as yaml from 'js-yaml'
import type { PipelineDefinition, StepDef, AtomicStepDef, ScriptStepDef } from './types'

/**
 * Minimal YAML loader for pipeline definitions.
 * Validates structure manually rather than relying on Zod v4 schema inference,
 * since Zod v4 type system has strict compatibility requirements.
 */
export class PipelineLoader {
  private validatedCount = 0

  async loadFromFile(filePath: string): Promise<PipelineDefinition> {
    const content = fs.readFileSync(filePath, 'utf-8')
    const raw = yaml.load(content) as Record<string, unknown> | undefined

    if (!raw || typeof raw !== 'object') {
      throw new Error(`${filePath}: invalid YAML — expected an object`)
    }

    const id = String(raw.id || '')
    if (!id) throw new Error(`${filePath}: missing required field "id"`)
    if (!Array.isArray(raw.steps) || raw.steps.length === 0) {
      throw new Error(`${filePath}: missing or empty "steps"`)
    }

    const steps: StepDef[] = raw.steps.map((s: unknown, i: number) =>
      this.validateStep(s, i, filePath)
    )

    // Validate dependency references
    this.validateDeps(steps, filePath)

    const pipeline: PipelineDefinition = {
      id,
      display_name: raw.display_name as string | undefined,
      description: raw.description as string | undefined,
      version: String(raw.version ?? '1.0'),
      steps,
      outputs: raw.outputs as PipelineDefinition['outputs'],
    }

    this.validatedCount++
    return pipeline
  }

  async loadFromDirectory(dirPath: string): Promise<PipelineDefinition[]> {
    const entries = fs.readdirSync(dirPath, { withFileTypes: true })
    const pipelines: PipelineDefinition[] = []

    for (const entry of entries) {
      if (!entry.isFile() || !entry.name.endsWith('.yaml')) continue
      const filePath = path.join(dirPath, entry.name)
      try {
        pipelines.push(await this.loadFromFile(filePath))
      } catch (err) {
        console.warn(`[PipelineLoader] Skipping ${filePath}: ${err}`)
      }
    }

    return pipelines
  }

  getValidatedCount(): number {
    return this.validatedCount
  }

  // ─── Private Validation ────────────────────────────────

  private validateStep(raw: unknown, index: number, filePath: string): StepDef {
    if (!raw || typeof raw !== 'object') {
      throw new Error(`${filePath}: step[${index}] is not an object`)
    }
    const s = raw as Record<string, unknown>
    const id = String(s.id || '')
    if (!id) throw new Error(`${filePath}: step[${index}] missing "id"`)

    const type = String(s.type || '')
    if (!['atomic_workflow', 'script', 'parallel'].includes(type)) {
      throw new Error(
        `${filePath}: step "${id}" has invalid type "${type}" (expected atomic_workflow/script/parallel)`
      )
    }

    switch (type) {
      case 'atomic_workflow':
        return this.validateAtomicStep(s, id, filePath)
      case 'script':
        return this.validateScriptStep(s, id, filePath)
      case 'parallel':
        return {
          id,
          type: 'parallel',
          steps: (Array.isArray(s.steps) ? s.steps : []).map(
           (sub: unknown, i: number): AtomicStepDef | ScriptStepDef => {
             const validated = this.validateStep(sub, i, filePath)
             if (validated.type === 'parallel') {
               throw new Error(`${filePath}: nested parallel steps not allowed`)
             }
             return validated
           }
         ),
          description: s.description as string | undefined,
          depends_on: this.asStringArray(s.depends_on),
        }
      default:
        throw new Error(`${filePath}: unhandled step type "${type}" for step "${id}"`)
    }
  }

  private validateAtomicStep(
    s: Record<string, unknown>,
    id: string,
    filePath: string
  ): AtomicStepDef {
    const workflow_id = String(s.workflow_id || '')
    if (!workflow_id) {
      throw new Error(`${filePath}: atomic step "${id}" missing "workflow_id"`)
    }

    const retry = s.retry as { max?: number; delay?: number } | undefined
    const fallback = s.fallback as
      | { action: string; workflow_id?: string; delay?: number }
      | undefined

    return {
      id,
      type: 'atomic_workflow',
      workflow_id,
      description: s.description as string | undefined,
      depends_on: this.asStringArray(s.depends_on),
      count: s.count != null ? Number(s.count) : undefined,
      inputs: (s.inputs as Record<string, string | number | boolean | null>) ?? {},
      outputs: (s.outputs as Record<string, string>) ?? {},
      retry: retry
        ? { max: retry.max ?? 2, delay: retry.delay ?? 2000 }
        : undefined,
      fallback: fallback
        ? {
            action: fallback.action as 'retry' | 'skip' | 'fallback' | 'abort',
            workflow_id: fallback.workflow_id,
            delay: fallback.delay,
          }
        : undefined,
    }
  }

  private validateScriptStep(
    s: Record<string, unknown>,
    id: string,
    filePath: string
  ): ScriptStepDef {
    const script = String(s.script || '')
    if (!script) {
      throw new Error(`${filePath}: script step "${id}" missing "script"`)
    }

    const retry = s.retry as { max?: number; delay?: number } | undefined

    return {
      id,
      type: 'script',
      script,
      description: s.description as string | undefined,
      depends_on: this.asStringArray(s.depends_on),
      inputs: (s.inputs as Record<string, string | number | boolean | null>) ?? {},
      outputs: (s.outputs as Record<string, string>) ?? {},
      retry: retry
        ? { max: retry.max ?? 2, delay: retry.delay ?? 2000 }
        : undefined,
    }
  }

  private validateDeps(steps: StepDef[], filePath: string): void {
    const ids = new Set(steps.map(s => s.id))
    for (const step of steps) {
      for (const dep of step.depends_on ?? []) {
        if (!ids.has(dep)) {
          throw new Error(
            `${filePath}: step "${step.id}" depends on "${dep}" which doesn't exist`
          )
        }
      }
    }
  }

  private asStringArray(value: unknown): string[] | undefined {
    if (Array.isArray(value)) return value.map(String)
    return undefined
  }
}