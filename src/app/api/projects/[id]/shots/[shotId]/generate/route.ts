/**
 * Frame generation route for a single shot.
 *
 * POST /api/projects/[id]/shots/[shotId]/generate
 *
 * Wraps image generation with RetryStrategy.
 * On exhaustion: sets shot status to "failed" and logs to task_logs.
 */

import { NextResponse } from 'next/server'
import { db } from '@/lib/db'
import { shots, taskLogs } from '@/lib/db/schema'
import { eq, and } from 'drizzle-orm'
import { assertProjectOwnership } from '@/lib/assert-project-ownership'
import { resolveImageProvider } from '@/lib/ai/provider-factory'
import { RetryStrategy } from '@/lib/retry'
import { id as genId } from '@/lib/id'
import { ratioToSize } from '@/lib/ai/size'

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; shotId: string }> }
) {
  const { id: projectId, shotId } = await params

  // Verify ownership
  if (!(await assertProjectOwnership(request, projectId))) {
    return NextResponse.json({ error: 'Not found' }, { status: 404 })
  }

  // Load shot
  const [shot] = await db
    .select()
    .from(shots)
    .where(and(eq(shots.id, shotId), eq(shots.projectId, projectId)))

  if (!shot) {
    return NextResponse.json({ error: 'Shot not found' }, { status: 404 })
  }

  const body = (await request.json()) as {
    prompt: string
    ratio?: string
    modelConfig?: import('@/lib/ai/provider-factory').ModelConfigPayload
  }

  if (!body.prompt) {
    return NextResponse.json({ error: 'No prompt provided' }, { status: 400 })
  }

  const size = ratioToSize(body.ratio)

  const runId = genId()
  const startedAt = new Date().toISOString()

  // Log start
  await db.insert(taskLogs).values({
    id: genId(),
    projectId,
    shotId,
    taskType: 'frame_generation',
    runId,
    stepId: 'frame-generate',
    stepName: 'Frame Generation',
    startedAt,
    status: 'running',
  })

  try {
    // Set status to generating
    await db
      .update(shots)
      .set({ status: 'generating' })
      .where(eq(shots.id, shotId))

    const ai = resolveImageProvider(body.modelConfig)

    const strategy = new RetryStrategy({
      maxRetries: 2,
      baseDelay: 2000,
      jitter: true,
      onRetry: (attempt, error) => {
        console.warn(`[FrameGenerate] Retry ${attempt} for shot ${shotId}: ${error.message}`)
      },
    })

    const imagePath = await strategy.execute(async () => {
      return ai.generateImage(body.prompt, { size })
    })

    // Mark success
    await db
      .update(shots)
      .set({ status: 'completed' })
      .where(eq(shots.id, shotId))

    const completedAt = new Date().toISOString()
    await db.insert(taskLogs).values({
      id: genId(),
      projectId,
      shotId,
      taskType: 'frame_generation',
      runId,
      stepId: 'frame-generate',
      stepName: 'Frame Generation',
      startedAt,
      completedAt,
      status: 'success',
      durationMs: Date.now() - new Date(startedAt).getTime(),
    })

    return NextResponse.json({ shotId, imagePath, status: 'completed' })
  } catch (err) {
    const errorMessage = err instanceof Error ? err.message : String(err)
    console.error(`[FrameGenerate] Failed for shot ${shotId}: ${errorMessage}`)

    // Mark shot as failed
    await db
      .update(shots)
      .set({ status: 'failed' })
      .where(eq(shots.id, shotId))

    const completedAt = new Date().toISOString()
    await db.insert(taskLogs).values({
      id: genId(),
      projectId,
      shotId,
      taskType: 'frame_generation',
      runId,
      stepId: 'frame-generate',
      stepName: 'Frame Generation',
      startedAt,
      completedAt,
      status: 'failed',
      durationMs: Date.now() - new Date(startedAt).getTime(),
      error: errorMessage,
      errorType: err instanceof Error ? err.name : 'UnknownError',
      retryCount: 2,
    })

    return NextResponse.json(
      { error: `Frame generation failed: ${errorMessage}` },
      { status: 500 }
    )
  }
}