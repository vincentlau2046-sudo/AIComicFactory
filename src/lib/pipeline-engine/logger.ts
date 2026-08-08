import type { DrizzleDB } from '@/lib/db'
import { taskLogs } from '@/lib/db/schema'

/**
 * PipelineRunLogger — structured execution logging at step level.
 *
 * Logs pipeline execution steps with timing, status, and error info.
 * Stores structured logs that can be written to DB via the task_logs table.
 */

export interface PipelineRunLog {
  runId: string
  stepId: string
  stepName: string
  startedAt: string       // ISO timestamp
  completedAt?: string
  status: 'running' | 'success' | 'failed' | 'retried'
  durationMs?: number
  error?: string
  errorType?: string
  retryCount?: number
  metadata?: Record<string, unknown>  // optional step-specific context
}

interface RunMeta {
  runId: string
  pipelineName: string
  inputs: Record<string, unknown>
  startedAt: string
  status: 'running' | 'success' | 'failed'
  steps: PipelineRunLog[]
  flushedStepKeys: Set<string>
}

export class PipelineRunLogger {
  private runs = new Map<string, RunMeta>()

  /**
   * Start tracking a new pipeline run.
   * Must be called before any steps are logged.
   */
  startRun(runId: string, pipelineName: string, inputs: Record<string, unknown>): void {
    this.runs.set(runId, {
      runId,
      pipelineName,
      inputs,
      startedAt: new Date().toISOString(),
      status: 'running',
      steps: [],
      flushedStepKeys: new Set(),
    })
  }

  /**
   * Start tracking a step within a pipeline run.
   * Creates a log entry with 'running' status.
   */
  startStep(step: {
    runId: string
    stepId: string
    stepName: string
    metadata?: Record<string, unknown>
  }): void {
    const run = this.runs.get(step.runId)
    if (!run) {
      console.warn(`[PipelineRunLogger] No active run for ${step.runId}, calling startRun first`)
      return
    }

    // Check for existing running step — end it as retried
    const existing = run.steps.find(s => s.stepId === step.stepId && s.status === 'running')
    if (existing) {
      existing.status = 'retried'
      existing.completedAt = new Date().toISOString()
      existing.durationMs = Date.now() - new Date(existing.startedAt).getTime()
      existing.retryCount = (existing.retryCount ?? 0) + 1
    }

    run.steps.push({
      runId: step.runId,
      stepId: step.stepId,
      stepName: step.stepName,
      startedAt: new Date().toISOString(),
      status: 'running',
      metadata: step.metadata,
    })
  }

  /**
   * Mark a step as completed with its final status.
   * Calculates duration automatically from the step's start time.
   */
  endStep(
    stepId: string,
    status: PipelineRunLog['status'],
    error?: Error,
    durationMs?: number
  ): void {
    // Find the step — search across all runs
    for (const run of this.runs.values()) {
      const step = run.steps.find(s => s.stepId === stepId && s.status === 'running')
      if (!step) continue

      step.status = status
      step.completedAt = new Date().toISOString()
      step.durationMs = durationMs ?? (Date.now() - new Date(step.startedAt).getTime())

      if (error) {
        step.error = error.message
        step.errorType = error.name
      }

      return
    }

    console.warn(`[PipelineRunLogger] No running step found for stepId: ${stepId}`)
  }

  /**
   * End the entire pipeline run with final status.
   */
  endRun(runId: string, status: 'success' | 'failed'): void {
    const run = this.runs.get(runId)
    if (!run) {
      console.warn(`[PipelineRunLogger] No active run for ${runId}`)
      return
    }
    run.status = status
  }

  /**
   * Get all structured log entries for a run.
   * Returns steps in insertion order with calculated durations.
   */
  getRunLog(runId?: string): PipelineRunLog[] {
    if (runId) {
      const run = this.runs.get(runId)
      return run?.steps ?? []
    }

    // Return all steps across all runs
    const allSteps: PipelineRunLog[] = []
    for (const run of this.runs.values()) {
      allSteps.push(...run.steps)
    }
    return allSteps
  }

  /**
   * Flush completed (unflushed) steps to the task_logs DB table.
   * Idempotent: already-flushed steps are skipped.
   * Returns the number of rows inserted.
   */
  async flush(
    runId: string,
    projectId: string,
    shotId: string,
    db: DrizzleDB,
  ): Promise<number> {
    const run = this.runs.get(runId)
    if (!run) {
      console.warn(`[PipelineRunLogger] No run found for flush: ${runId}`)
      return 0
    }

    const pending = run.steps.filter(
      (s) =>
        s.completedAt !== undefined &&
        s.status !== 'running' &&
        !run.flushedStepKeys.has(`${s.stepId}:${s.startedAt}`),
    )

    if (pending.length === 0) return 0

    const rows = pending.map((s) => ({
      id: crypto.randomUUID(),
      projectId,
      shotId,
      taskType: run.pipelineName,
      runId,
      stepId: s.stepId,
      stepName: s.stepName,
      startedAt: s.startedAt,
      completedAt: s.completedAt,
      status: s.status,
      durationMs: s.durationMs,
      error: s.error,
      errorType: s.errorType,
      retryCount: s.retryCount,
      metadata: s.metadata ? JSON.stringify(s.metadata) : undefined,
    }))

    await db.insert(taskLogs).values(rows)

    for (const s of pending) {
      run.flushedStepKeys.add(`${s.stepId}:${s.startedAt}`)
    }

    console.log(`[PipelineRunLogger] Flushed ${rows.length} steps for run ${runId}`)
    return rows.length
  }

  /**
   * Get full run metadata.
   */
  getRunMeta(runId: string): RunMeta | undefined {
    return this.runs.get(runId)
  }

  /**
   * Clear all stored logs — useful for testing or memory management.
   */
  clear(): void {
    this.runs.clear()
  }
}

// Singleton for app-wide use
export const pipelineLogger = new PipelineRunLogger()