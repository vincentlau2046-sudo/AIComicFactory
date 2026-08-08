/**
 * Video generation route.
 *
 * POST /api/projects/[id]/video/generate
 *
 * Wraps video generation with RetryStrategy and ComfyUI reconnection.
 * On exhaustion: sets shot status to "failed" and logs to task_logs.
 */

import { NextResponse } from 'next/server'
import { db } from '@/lib/db'
import { shots, taskLogs } from '@/lib/db/schema'
import { eq, and } from 'drizzle-orm'
import { assertProjectOwnership } from '@/lib/assert-project-ownership'
import { resolveVideoProvider } from '@/lib/ai/provider-factory'
import { RetryStrategy } from '@/lib/retry'
import { id as genId } from '@/lib/id'
import type { ComfyUIClient } from '@/lib/comfyui/client'
import type { VideoProvider } from '@/lib/ai/types'

/** Error names that indicate connection issues */
const CONNECTION_ERROR_NAMES = [
  'ComfyUIConnectionError',
  'FetchError',
  'AbortError',
  'TimeoutError',
  'NetworkError',
  'TypeError',
]

interface VideoGenerateBody {
  shotId: string
  prompt: string
  firstFrame?: string
  lastFrame?: string
  initialImage?: string
  duration: number
  modelConfig?: import('@/lib/ai/provider-factory').ModelConfigPayload
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id: projectId } = await params

  // Verify ownership
  if (!(await assertProjectOwnership(request, projectId))) {
    return NextResponse.json({ error: 'Not found' }, { status: 404 })
  }

  const body = (await request.json()) as VideoGenerateBody

  if (!body.shotId || !body.prompt) {
    return NextResponse.json({ error: 'shotId and prompt are required' }, { status: 400 })
  }

  // Load shot
  const [shot] = await db
    .select()
    .from(shots)
    .where(and(eq(shots.id, body.shotId), eq(shots.projectId, projectId)))

  if (!shot) {
    return NextResponse.json({ error: 'Shot not found' }, { status: 404 })
  }

  const runId = genId()
  const startedAt = new Date().toISOString()

  // Log start
  await db.insert(taskLogs).values({
    id: genId(),
    projectId,
    shotId: body.shotId,
    taskType: 'video_generation',
    runId,
    stepId: 'video-generate',
    stepName: 'Video Generation',
    startedAt,
    status: 'running',
  })

  let reconnectAttempts = 0

  try {
    // Set shot to generating
    await db
      .update(shots)
      .set({ status: 'generating' })
      .where(eq(shots.id, body.shotId))

    const videoProvider = resolveVideoProvider(body.modelConfig)

    // Build retry strategy with connection error detection and reconnect callback
    let reconnectAttempts = 0
    const strategy = new RetryStrategy({
      maxRetries: 3,
      baseDelay: 3000,
      maxDelay: 30000,
      jitter: true,
      retryableErrors: CONNECTION_ERROR_NAMES,
      onRetry: async (attempt, error) => {
        console.warn(`[VideoGenerate] Retry ${attempt} for shot ${body.shotId}: ${error.message}`)

        // Attempt ComfyUI reconnect if connection error
        if (CONNECTION_ERROR_NAMES.includes(error.name) || error.message.includes('Connection')) {
          reconnectAttempts++
          try {
            // Try to access the internal ComfyUI client from the provider
            const comfyuiProvider = videoProvider as unknown as {
              client?: ComfyUIClient
              ensureConnected?: () => Promise<boolean>
            }
            if (comfyuiProvider.ensureConnected) {
              const connected = await comfyuiProvider.ensureConnected()
              console.log(`[VideoGenerate] ComfyUI reconnect ${reconnectAttempts}: ${connected ? 'OK' : 'FAILED'}`)
            } else if (comfyuiProvider.client?.reconnect) {
              const connected = await comfyuiProvider.client.reconnect()
              console.log(`[VideoGenerate] ComfyUI reconnect ${reconnectAttempts}: ${connected ? 'OK' : 'FAILED'}`)
            }
          } catch (reconnectErr) {
            console.error(`[VideoGenerate] Reconnect attempt failed: ${reconnectErr}`)
          }
        }
      },
    })

    const result = await strategy.execute(async () => {
      // Build correct discriminated union type for VideoGenerateParams
      if (body.firstFrame && body.lastFrame) {
        // Keyframe mode
        return videoProvider.generateVideo({
          prompt: body.prompt,
          firstFrame: body.firstFrame,
          lastFrame: body.lastFrame,
          duration: body.duration,
          ratio: '16:9',
        })
      } else if (body.initialImage) {
        // Reference mode
        return videoProvider.generateVideo({
          prompt: body.prompt,
          initialImage: body.initialImage,
          duration: body.duration,
          ratio: '16:9',
        })
      } else {
        // Text-to-video mode
        throw new Error('At least one of firstFrame+lastFrame or initialImage must be provided')
      }
    })

    // Mark shot as completed
    await db
      .update(shots)
      .set({ status: 'completed' })
      .where(eq(shots.id, body.shotId))

    const completedAt = new Date().toISOString()
    await db.insert(taskLogs).values({
      id: genId(),
      projectId,
      shotId: body.shotId,
      taskType: 'video_generation',
      runId,
      stepId: 'video-generate',
      stepName: 'Video Generation',
      startedAt,
      completedAt,
      status: 'success',
      durationMs: Date.now() - new Date(startedAt).getTime(),
    })

    return NextResponse.json({
      shotId: body.shotId,
      filePath: result.filePath,
      status: 'completed',
      reconnectAttempts,
    })
  } catch (err) {
    const errorMessage = err instanceof Error ? err.message : String(err)
    console.error(`[VideoGenerate] Failed for shot ${body.shotId}: ${errorMessage}`)

    // Mark shot as failed
    await db
      .update(shots)
      .set({ status: 'failed' })
      .where(eq(shots.id, body.shotId))

    const completedAt = new Date().toISOString()
    await db.insert(taskLogs).values({
      id: genId(),
      projectId,
      shotId: body.shotId,
      taskType: 'video_generation',
      runId,
      stepId: 'video-generate',
      stepName: 'Video Generation',
      startedAt,
      completedAt,
      status: 'failed',
      durationMs: Date.now() - new Date(startedAt).getTime(),
      error: errorMessage,
      errorType: err instanceof Error ? err.name : 'UnknownError',
      retryCount: 3,
      metadata: JSON.stringify({ reconnectAttempts }),
    })

    return NextResponse.json(
      { error: `Video generation failed: ${errorMessage}` },
      { status: 500 }
    )
  }
}