/**
 * WorkflowRegistry — hot-pluggable atomic workflow metadata container
 *
 * Auto-discovers workflow.json + meta.yaml pairs from a directory.
 * Each workflow = one subdirectory containing both files.
 * Use scanFromDirectory() to load, or register()/unregister() for runtime hot-plug.
 */

import fs from 'node:fs'
import path from 'node:path'
import * as yaml from 'js-yaml'
import { type ResolvedWorkflow, type WorkflowMeta, WorkflowNotFoundError } from './types'

export class WorkflowRegistry {
  private workflows = new Map<string, ResolvedWorkflow>()

  // ─── Discovery ────────────────────────────────────────────

  /**
   * Scan a directory for workflow definitions.
   *
   * Expected structure:
   *   <dir>/<workflow-name>/
   *     ├── workflow.json     (ComfyUI API format JSON)
   *     └── meta.yaml         (WorkflowMeta YAML)
   *
   * Or flat file pairs in older format:
   *   <dir>/<workflow-name>.json
   *   <dir>/<workflow-name>.meta.yaml
   */
  async scanFromDirectory(dir: string): Promise<string[]> {
    if (!fs.existsSync(dir)) {
      throw new Error(`Workflow directory not found: ${dir}`)
    }

    const entries = fs.readdirSync(dir, { withFileTypes: true })
    const loaded: string[] = []

    // Group files by base name
    const groups = new Map<string, { json?: string; meta?: string }>()

    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name)

      if (entry.isDirectory()) {
        // Subdirectory: workflow-name/workflow.json + meta.yaml
        const jsonPath = path.join(fullPath, 'workflow.json')
        const metaPath = path.join(fullPath, 'meta.yaml')
        const hasJson = fs.existsSync(jsonPath)
        const hasMeta = fs.existsSync(metaPath)

        if (hasJson && hasMeta) {
          try {
            this.registerFromFiles(entry.name, jsonPath, metaPath)
            loaded.push(entry.name)
          } catch (err) {
            console.warn(`[WorkflowRegistry] Skipping ${entry.name}: ${err}`)
          }
        }
        continue
      }

      // Flat file: only process .json and .meta.yaml
      const name = entry.name
      if (name.endsWith('.json') && !name.endsWith('.meta.json')) {
        const base = name.slice(0, -5)
        const g = groups.get(base) || {}
        g.json = fullPath
        groups.set(base, g)
      } else if (name.endsWith('.meta.yaml')) {
        const base = name.slice(0, -10)
        const g = groups.get(base) || {}
        g.meta = fullPath
        groups.set(base, g)
      }
    }

    // Register flat file pairs
    for (const [baseName, files] of groups) {
      if (files.json && files.meta) {
        try {
          this.registerFromFiles(baseName, files.json, files.meta)
          loaded.push(baseName)
        } catch (err) {
          console.warn(`[WorkflowRegistry] Skipping ${baseName}: ${err}`)
        }
      }
    }

    return loaded
  }

  // ─── Registration ─────────────────────────────────────────

  /** Register a workflow from JSON and meta files */
  registerFromFiles(name: string, jsonPath: string, metaPath: string): void {
    const metaYaml = fs.readFileSync(metaPath, 'utf-8')
    const meta = yaml.load(metaYaml) as WorkflowMeta

    // Validate meta
    if (!meta.name) throw new Error('meta.yaml must contain "name"')
    if (!Array.isArray(meta.inputs)) throw new Error('meta.yaml must contain "inputs" array')
    if (!Array.isArray(meta.outputs)) throw new Error('meta.yaml must contain "outputs" array')

    let json: Record<string, unknown>
    try {
      json = JSON.parse(fs.readFileSync(jsonPath, 'utf-8'))
    } catch {
      throw new Error(`Invalid workflow.json: ${jsonPath}`)
    }

    const wfId = meta.name

    this.workflows.set(wfId, {
      meta,
      workflowJson: json,
      sourcePath: jsonPath,
    })
  }

  /** Register a workflow at runtime (hot-plug) */
  register(wfId: string, meta: WorkflowMeta, workflowJson: Record<string, unknown>): void {
    if (!meta.name) meta.name = wfId
    this.workflows.set(wfId, { meta, workflowJson, sourcePath: '' })
  }

  /** Remove a workflow at runtime */
  unregister(wfId: string): boolean {
    return this.workflows.delete(wfId)
  }

  // ─── Query ────────────────────────────────────────────────

  /** Get a workflow by ID — throws if not found */
  get(wfId: string): ResolvedWorkflow {
    const wf = this.workflows.get(wfId)
    if (!wf) throw new WorkflowNotFoundError(wfId)
    return wf
  }

  /** Check if a workflow exists */
  has(wfId: string): boolean {
    return this.workflows.has(wfId)
  }

  /** List all registered workflow IDs, optionally filtered by gpu_model */
  list(filter?: { gpuModel?: string }): string[] {
    const all = Array.from(this.workflows.keys())
    if (!filter?.gpuModel) return all
    return all.filter(id => this.workflows.get(id)?.meta.gpu_model === filter.gpuModel)
  }

  /** Get all registered workflows */
  getAll(): Map<string, ResolvedWorkflow> {
    return new Map(this.workflows)
  }

  /** Number of registered workflows */
  get size(): number {
    return this.workflows.size
  }
}