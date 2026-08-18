import { dequeueTask, completeTask, failTask } from "./queue";
import type { TaskHandlerMap, Task } from "./types";

const POLL_INTERVAL_MS = 2000;
const COMFYUI_BASE_URL = process.env.COMFYUI_BASE_URL || 'http://localhost:8188';

let isRunning = false;
let handlers: TaskHandlerMap = {};

// ─── ComfyUI health cache ───
let comfyHealthy = true;
let comfyLastCheck = 0;

async function checkComfyHealth(): Promise<boolean> {
  const now = Date.now();
  // Healthy: 30s cache. Unhealthy: 10s cache (faster recovery detection).
  const ttl = comfyHealthy ? 30_000 : 10_000;
  if (now - comfyLastCheck < ttl) return comfyHealthy;
  try {
    const res = await fetch(`${COMFYUI_BASE_URL}/system_stats`, { signal: AbortSignal.timeout(3000) });
    comfyHealthy = res.ok;
  } catch (err) {
    comfyHealthy = false;
    console.error(`[Worker] ComfyUI health check failed: ${err instanceof Error ? err.message : String(err)}`);
  }
  comfyLastCheck = now;
  return comfyHealthy;
}

export function registerHandlers(newHandlers: TaskHandlerMap) {
  handlers = { ...handlers, ...newHandlers };
}

async function processTask(task: Task) {
  const handler = task.type ? handlers[task.type] : undefined;
  if (!handler) {
    await failTask(task.id, `No handler registered for task type: ${task.type}`);
    return;
  }

  try {
    const result = await handler(task);
    await completeTask(task.id, result);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    await failTask(task.id, message);
  }
}

async function poll() {
  if (!isRunning) return;

  try {
    const ok = await checkComfyHealth();
    if (!ok) console.log("[Worker] ComfyUI offline, skipping ComfyUI tasks");
    const task = await dequeueTask({ skipComfy: !ok });
    if (task) {
      await processTask(task);
    }
  } catch (err) {
    console.error("[TaskWorker] Poll error:", err);
  }

  if (isRunning) {
    setTimeout(poll, POLL_INTERVAL_MS);
  }
}

export function startWorker() {
  if (isRunning) return;
  isRunning = true;
  console.log("[TaskWorker] Started polling every", POLL_INTERVAL_MS, "ms");
  poll();
}

export function stopWorker() {
  isRunning = false;
  console.log("[TaskWorker] Stopped");
}
