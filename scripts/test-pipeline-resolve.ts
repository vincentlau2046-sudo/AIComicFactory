/**
 * Direct pipeline resolution test - read runtime values
 */
import { PipelineEngine } from '@/lib/pipeline-engine'
import type { PipelineInputs } from '@/lib/pipeline-engine'

// Minimal pipeline inputs mirroring what frame-generate.ts sends
const inputs: PipelineInputs = {
  prompt: '=== LAST_FRAME_PROMPT ===',
  referenceImages: ['/path/to/character_ref.png'],
  first_prompt: '=== FIRST_FRAME_PROMPT ===',
  last_prompt: '=== LAST_FRAME_PROMPT ===',
  scene_prompt: '=== SHOT_PROMPT_TEXT ===',
  seed: 99,
  width: 1024,
  height: 1024,
}

console.log('PipelineInputs:', Object.keys(inputs))
console.log('  first_prompt:', (inputs as any).first_prompt.slice(0, 30))
console.log('  last_prompt:', (inputs as any).last_prompt.slice(0, 30))
console.log('  scene_prompt:', (inputs as any).scene_prompt.slice(0, 30))
console.log('  seed:', (inputs as any).seed)