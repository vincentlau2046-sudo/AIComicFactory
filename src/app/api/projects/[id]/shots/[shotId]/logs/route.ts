import { NextResponse } from 'next/server'
import { eq, and, desc } from 'drizzle-orm'
import { db } from '@/lib/db'
import { taskLogs } from '@/lib/db/schema'

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string; shotId: string }> }
) {
  const { id: projectId, shotId } = await params
  const { searchParams } = new URL(req.url)

  const status = searchParams.get('status')
  const limit = searchParams.get('limit')

  const conditions = [eq(taskLogs.shotId, shotId)]
  if (status) {
    conditions.push(eq(taskLogs.status, status))
  }

  const logs = await db
    .select({
      id: taskLogs.id,
      runId: taskLogs.runId,
      stepId: taskLogs.stepId,
      stepName: taskLogs.stepName,
      status: taskLogs.status,
      startedAt: taskLogs.startedAt,
      completedAt: taskLogs.completedAt,
      durationMs: taskLogs.durationMs,
      error: taskLogs.error,
      errorType: taskLogs.errorType,
      retryCount: taskLogs.retryCount,
      taskType: taskLogs.taskType,
    })
    .from(taskLogs)
    .where(and(...conditions))
    .orderBy(desc(taskLogs.startedAt))
    .limit(limit ? parseInt(limit) : 50)

  return NextResponse.json({ logs })
}
