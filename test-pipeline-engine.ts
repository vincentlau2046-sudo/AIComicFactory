/**
 * Pipeline Engine 集成测试
 *
 * Tests:
 *   1. PipelineLoader — load YAML definitions
 *   2. TemplateResolver — ${params.x} and ${steps.y.z} resolution
 *   3. GPUScheduler — model family transitions
 *   4. DAGExecutor — topological execution with mock atomic steps
 *
 * Run: npx --package tsx tsx test-pipeline-engine.ts
 */

import path from 'node:path'
import { PipelineLoader } from '@/lib/pipeline-engine/loader'
import { resolveTemplate, resolveInputs } from '@/lib/pipeline-engine/template'
import { GPUScheduler } from '@/lib/pipeline-engine/gpu-scheduler'
import type { ResolveContext } from '@/lib/pipeline-engine/types'

async function main() {
  const PIPELINES_DIR = path.join(process.cwd(), 'src', 'lib', 'pipeline-engine', 'pipelines')
  const passed: string[] = []
  const failed: string[] = []

  function assert(condition: boolean, msg: string) {
  if (condition) {
    passed.push(msg)
    console.log(`  ✅ ${msg}`)
  } else {
    failed.push(msg)
    console.log(`  ❌ ${msg}`)
  }
}

// ===== Test 1: PipelineLoader =====
console.log('\n🧪 Test 1: PipelineLoader')

const loader = new PipelineLoader()

// Load character-image pipeline
const characterImage = await loader.loadFromFile(
  path.join(PIPELINES_DIR, 'character-image.yaml')
)
assert(characterImage.id === 'character-image', 'character-image id matches')
assert(characterImage.steps.length === 5, 'character-image has 5 steps')
assert(characterImage.steps[0].type === 'atomic_workflow', 'step 0 is atomic_workflow')
assert(characterImage.steps[0].id === 'gen_front', 'step 0 id is gen_front')
assert(
  (characterImage.steps[0] as any).workflow_id === 'qwen-2512-t2i',
  'step 0 workflow_id is qwen-2512-t2i'
)

// Check DAG dependency references
const stepIds = new Set(characterImage.steps.map(s => s.id))
assert(stepIds.has('gen_front'), 'has gen_front')
assert(stepIds.has('gen_angle_left'), 'has gen_angle_left')
assert(stepIds.has('merge_fourview'), 'has merge_fourview')
const mergeStep = characterImage.steps.find(s => s.id === 'merge_fourview')!
assert(mergeStep.type === 'script', 'merge_fourview is script step')
assert(mergeStep.depends_on?.length === 4, 'merge_fourview depends on 4 steps')

// Load frame-generate pipeline
const frameGenerate = await loader.loadFromFile(
  path.join(PIPELINES_DIR, 'frame-generate.yaml')
)
assert(frameGenerate.steps.length === 2, 'frame-generate has 2 steps')
assert(frameGenerate.steps[1].depends_on?.[0] === 'gen_first_frame', 'last_frame depends on first_frame')

// Load video-generate pipeline
const videoGenerate = await loader.loadFromFile(
  path.join(PIPELINES_DIR, 'video-generate.yaml')
)
assert(videoGenerate.steps.length === 1, 'video-generate has 1 step')

// Load from directory
const allPipelines = await loader.loadFromDirectory(PIPELINES_DIR)
assert(allPipelines.length === 3, `loaded ${allPipelines.length} pipelines`)

// ===== Test 2: TemplateResolver =====
console.log('\n🧪 Test 2: TemplateResolver')

const ctx: ResolveContext = {
  inputs: { prompt: 'a cat', seed: 42 },
  steps: new Map([
    [
      'gen_front',
      {
        stepId: 'gen_front',
        outputs: ['/tmp/front.png'],
        named: { front_image: '/tmp/front.png' },
        duration: 1000,
      },
    ],
  ]),
  env: { UPLOAD_DIR: '/tmp' },
}

// Resolve params
const promptResult = resolveTemplate('${params.prompt}', ctx)
assert(promptResult === 'a cat', 'resolves ${params.prompt} → "a cat"')

const seedResult = resolveTemplate('${params.seed}', ctx)
assert(seedResult === 42, 'resolves ${params.seed} → 42')

// Resolve steps
const frontResult = resolveTemplate('${steps.gen_front.outputs[0]}', ctx)
assert(frontResult === '/tmp/front.png', 'resolves ${steps.gen_front.outputs[0]}')

// Resolve named output
const namedResult = resolveTemplate('${steps.gen_front.front_image}', ctx)
assert(namedResult === '/tmp/front.png', 'resolves ${steps.gen_front.front_image}')

// Resolve env
const envResult = resolveTemplate('${env.UPLOAD_DIR}', ctx)
assert(envResult === '/tmp', 'resolves ${env.UPLOAD_DIR}')

// Interpolation in text
const interpResult = resolveTemplate('Prompt: ${params.prompt}, seed=${params.seed}', ctx)
assert(interpResult === 'Prompt: a cat, seed=42', 'interpolation in text')

// Null/boolean passthrough
assert(resolveTemplate(null, ctx) === null, 'null passthrough')
assert(resolveTemplate(true, ctx) === true, 'boolean passthrough')

// Arithmetic expressions (P0-4 fix)
const arithResult = resolveTemplate('${params.seed + 1}', ctx)
assert(arithResult === 43, 'resolves ${params.seed + 1} → 43')

const arithSub = resolveTemplate('${params.seed - 2}', ctx)
assert(arithSub === 40, 'resolves ${params.seed - 2} → 40')

const arithMul = resolveTemplate('${params.seed * 3}', ctx)
assert(arithMul === 126, 'resolves ${params.seed * 3} → 126')

// Array indexing (P0-5 fix)
const arrCtx: ResolveContext = {
  inputs: { prompt: 'test', referenceImages: ['/tmp/ref1.png', '/tmp/ref2.png'] },
  steps: new Map(),
  env: {},
}
const arrResult = resolveTemplate('${params.referenceImages[0]}', arrCtx)
assert(arrResult === '/tmp/ref1.png', 'resolves ${params.referenceImages[0]}')

const arrResult2 = resolveTemplate('${params.referenceImages[1]}', arrCtx)
assert(arrResult2 === '/tmp/ref2.png', 'resolves ${params.referenceImages[1]}')

// ===== Test 3: Input Resolver =====
console.log('\n🧪 Test 3: Input Resolver')

const resolved = resolveInputs(
  {
    prompt: '${params.prompt}',
    seed: '${params.seed}',
    image: '${steps.gen_front.outputs[0]}',
    steps: 20,
    cfg: 3.5,
  },
  ctx
)
assert(resolved.prompt === 'a cat', 'resolved prompt')
assert(resolved.image === '/tmp/front.png', 'resolved image path')
assert(resolved.steps === 20, 'literal steps passes through')

// ===== Test 4: GPUScheduler =====
console.log('\n🧪 Test 4: GPUScheduler')

let freeCalled = false
let freeCount = 0
const gpu = new GPUScheduler(async () => {
  freeCalled = true
  freeCount++
})

// First transition — no previous model, no free needed
await gpu.onStepTransition('qwen_2512')
assert(!freeCalled, 'no free on first transition')
assert(gpu.getCurrentFamily() === 'qwen-image', 'family is qwen-image')

// Same family — no free
freeCalled = false
await gpu.onStepTransition('qwen_2511')
assert(!freeCalled, 'no free on same-family transition')

// Different family — free called
freeCalled = false
await gpu.onStepTransition('minimax_h3')
assert(freeCalled, 'free on cross-family transition')
assert(freeCount === 1, 'free count = 1')

// Back to qwen — free called again
freeCalled = false
await gpu.onStepTransition('qwen_2512')
assert(freeCalled, 'free on cross-family back')
assert(freeCount === 2, 'free count = 2')

// CPU step — free called
freeCalled = false
await gpu.onStepTransition(undefined)
assert(freeCalled, 'free on CPU transition')

// Finalize
freeCalled = false
await gpu.finalize()
assert(gpu.getCurrentFamily() === null, 'family reset after finalize')

  // ===== Summary =====
  console.log(`\n${'='.repeat(50)}`)
  console.log(`Result: ${passed.length} passed, ${failed.length} failed`)

  if (failed.length > 0) {
    process.exit(1)
  }
}

main().catch(err => {
  console.error('Test failed:', err)
  process.exit(1)
})