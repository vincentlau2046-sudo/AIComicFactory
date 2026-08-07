import { execSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { resolveInputs } from '../template'
import type { ScriptStepDef, ResolveContext, StepOutput } from '../types'

/**
 * Executes a script step by:
 * 1. Resolving template expressions
 * 2. Setting input file paths as environment variables
 * 3. Spawning the script (Python/Shell)
 * 4. Collecting output files from the output directory
 */
export class ScriptStepRunner {
  private readonly scriptsDir: string

  constructor(scriptsDir: string) {
    this.scriptsDir = scriptsDir
  }

  async execute(
    step: ScriptStepDef,
    ctx: ResolveContext,
    opts: { outputDir: string }
  ): Promise<StepOutput> {
    const startTime = Date.now()
    const resolvedInputs = resolveInputs(step.inputs, ctx)
    const stepOutputDir = path.join(opts.outputDir, step.id)
    fs.mkdirSync(stepOutputDir, { recursive: true })

    // Build environment variables for the script
    const env: Record<string, string> = {
      ...Object.fromEntries(
        Object.entries(resolvedInputs).map(([k, v]) => [
          `PIPELINE_${k.toUpperCase()}`,
          v != null ? String(v) : '',
        ])
      ),
      PIPELINE_STEP_ID: step.id,
      PIPELINE_OUTPUT_DIR: stepOutputDir,
    }

    // Find the script
    const scriptPath = this.resolveScript(step.script)

    const maxRetries = step.retry?.max ?? 0
    let lastError: Error | undefined

    for (let attempt = 0; attempt <= maxRetries; attempt++) {
      try {
        execSync(scriptPath, {
          env: { ...process.env, ...env },
          cwd: stepOutputDir,
          stdio: 'pipe',
          timeout: 300_000, // 5 minutes
        })
        lastError = undefined
        break
      } catch (err) {
        lastError = err instanceof Error ? err : new Error(String(err))
        if (attempt < maxRetries) {
          await sleep(step.retry?.delay ?? 2000)
        }
      }
    }

    if (lastError) throw lastError

    // Collect output files from the output directory (sorted for deterministic ordering)
    const outputs = fs.readdirSync(stepOutputDir)
      .sort()
      .map(f => path.join(stepOutputDir, f))
      .filter(f => fs.statSync(f).isFile())

    // Build named output map from step definition
    const named: Record<string, string> = {}
    let idx = 0
    for (const [name] of Object.entries(step.outputs)) {
      if (idx < outputs.length) {
        named[name] = outputs[idx]
        idx++
      }
    }

    return {
      stepId: step.id,
      outputs,
      named,
      duration: Date.now() - startTime,
    }
  }

  private resolveScript(name: string): string {
    // Check if it's an absolute or relative path
    if (fs.existsSync(name)) return name

    // Check scripts dir
    const fromScripts = path.join(this.scriptsDir, name)
    if (fs.existsSync(fromScripts)) return fromScripts

    // Check as a Python module (name.py)
    const pyPath = name.endsWith('.py') ? name : `${name}.py`
    const fromScriptsPy = path.join(this.scriptsDir, pyPath)
    if (fs.existsSync(fromScriptsPy)) return fromScriptsPy

    // Fallback: try PATH (no shell injection — use execFileSync)
    try {
      const { execFileSync } = require('node:child_process') as typeof import('node:child_process')
      const result = execFileSync('which', [name], { encoding: 'utf-8', stdio: 'pipe' }).trim()
      return result || name
    } catch {
      throw new Error(
        `Script "${name}" not found. Checked: ${name}, ${fromScripts}, ${fromScriptsPy}`
      )
    }
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms))
}