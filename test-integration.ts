#!/usr/bin/env tsx
/**
 * ComfyUIProvider 集成测试
 *
 * 测试全部 7 个原子工作流的端到端链路：
 *   1. qwen-2512-t2i       → 纯文生图
 *   2. qwen-2511-edit       → 单图编辑
 *   3. qwen-2511-edit-plus  → 多参考图
 *   4. qwen-2511-edit-multiangle → 多角度
 *   5. h3-t2v               → 文生视频+音频
 *   6. h3-i2v               → 首帧→视频
 *   7. h3-r2v               → 多参考图→视频
 *
 * 用法: tsx test-integration.ts [--skip-h3]
 *   --skip-h3: 跳过 H3 视频测试（耗时较长）
 */

import fs from 'node:fs'
import path from 'node:path'
import { ComfyUIClient } from './src/lib/comfyui/client'
import { WorkflowRegistry } from './src/lib/comfyui/registry'
import { AtomicWorkflowExecutor } from './src/lib/comfyui/executor'

const WORKFLOWS_DIR = '/home/vince/ComfyUI/workflows/AIComicFactory/atomic'
const OUTPUT_DIR = '/tmp/aicf-test-outputs'
const TEST_PROMPT = 'A serene Japanese garden with cherry blossoms, koi pond, stone lantern, morning light'
const NEGATIVE_PROMPT = 'nsfw, low quality, blurry, distorted, text, watermark'

async function main() {
  const skipH3 = process.argv.includes('--skip-h3')
  fs.mkdirSync(OUTPUT_DIR, { recursive: true })

  console.log('='.repeat(60))
  console.log('🧪 AICF ComfyUIProvider 集成测试')
  console.log(`  工作流目录: ${WORKFLOWS_DIR}`)
  console.log(`  输出目录: ${OUTPUT_DIR}`)
  console.log(`  跳过 H3: ${skipH3}`)
  console.log('='.repeat(60))
  console.log()

  // ── Initialize ──
  const client = new ComfyUIClient({ baseUrl: 'http://localhost:8188' })
  const registry = new WorkflowRegistry()
  const executor = new AtomicWorkflowExecutor(client, registry)

  // ── Health check ──
  console.log('🔍 ComfyUI health check...')
  const ok = await client.healthCheck()
  if (!ok) {
    console.error('❌ ComfyUI 不可达。请先启动 ComfyUI: python main.py --listen --port 8188')
    process.exit(1)
  }
  console.log('   ✅ 可达')
  console.log()

  const queue = await client.getQueue()
  console.log(`  队列: running=${queue.running}, pending=${queue.pending}`)
  if (queue.running > 0 || queue.pending > 0) {
    console.log('  ⚠️  队列非空，将排队等待...')
  }
  console.log()

  // ── Scan workflows ──
  console.log('🔍 扫描工作流...')
  const loaded = await registry.scanFromDirectory(WORKFLOWS_DIR)
  console.log(`   已加载 ${loaded.length} 个工作流: ${loaded.join(', ')}`)
  console.log()

  // ════════════════════════════════════════════════
  // Test 1: qwen-2512-t2i — 纯文生图
  // ════════════════════════════════════════════════
  console.log('─'.repeat(50))
  console.log('🧪 Test 1: qwen-2512-t2i — 纯文生图')
  console.log('─'.repeat(50))
  try {
    const result = await executor.execute('qwen-2512-t2i', {
      prompt: TEST_PROMPT,
      negative_prompt: NEGATIVE_PROMPT,
      steps: 8,   // 减少步数加快测试
      seed: 42,
      width: 512,
      height: 512,
    }, { outputDir: OUTPUT_DIR })

    console.log(`   status: ${result.status}`)
    console.log(`   duration: ${result.duration}ms`)
    console.log(`   seed: ${result.seed}`)
    console.log(`   outputs: ${result.outputs.length}`)
    for (const o of result.outputs) {
      const fileSize = fs.statSync(o.localPath).size
      console.log(`     📄 ${o.type}: ${o.localPath} (${fileSize} bytes)`)
      (globalThis as any).testImagePath = o.localPath
    }
    if (result.status === 'success' && result.outputs.length > 0) {
      console.log('   ✅ PASS')
    } else {
      console.log('   ❌ FAIL: 无输出')
    }
  } catch (err) {
    console.error(`   ❌ FAIL: ${err instanceof Error ? err.message : err}`)
  }
  console.log()

  // ════════════════════════════════════════════════
  // Test 2: qwen-2511-edit — 单图编辑
  // ════════════════════════════════════════════════
  console.log('─'.repeat(50))
  console.log('🧪 Test 2: qwen-2511-edit — 单图编辑')
  console.log('─'.repeat(50))
  try {
    // Use the output from Test 1 as reference
    const refImage = await findTestImage(OUTPUT_DIR)
    if (!refImage) {
      console.log('   ⚠️  无参考图，生成一张...')
      const gen = await executor.execute('qwen-2512-t2i', {
        prompt: 'A simple green apple on a white table',
        steps: 4,
        seed: 1,
        width: 512,
        height: 512,
      }, { outputDir: OUTPUT_DIR })
      if (gen.status === 'success' && gen.outputs.length > 0) {
        await executor.execute('qwen-2511-edit-scene-composite', {
          scene_prompt: 'a wooden table with a plate',
          composite_prompt: 'Picture 1 on the plate, still life photography',
          character_ref: gen.outputs[0].localPath,
          steps: 4,
          seed: 2,
        }, { outputDir: OUTPUT_DIR })
        console.log('   ✅ PASS')
      } else {
        console.log('   ⚠️  SKIP: 无法生成参考图')
      }
    } else {
      const result = await executor.execute('qwen-2511-edit-scene-composite', {
        scene_prompt: 'a wooden table with a plate, morning light',
        composite_prompt: 'Picture 1 on the plate, still life photography, soft lighting',
        character_ref: refImage,
        steps: 4,
        seed: 2,
      }, { outputDir: OUTPUT_DIR })
      console.log(`   status: ${result.status}, duration: ${result.duration}ms, outputs: ${result.outputs.length}`)
      for (const o of result.outputs) {
        console.log(`     📄 ${o.type}: ${path.basename(o.localPath)}`)
      }
      console.log(result.status === 'success' && result.outputs.length > 0 ? '   ✅ PASS' : '   ❌ FAIL')
    }
  } catch (err) {
    console.error(`   ❌ FAIL: ${err instanceof Error ? err.message : err}`)
  }
  console.log()

  // ════════════════════════════════════════════════
  // Test 3: qwen-2511-edit-plus — 多参考图
  // ════════════════════════════════════════════════
  console.log('─'.repeat(50))
  console.log('🧪 Test 3: qwen-2511-edit-plus — 多参考图')
  console.log('─'.repeat(50))
  try {
    const images = await collectImages(OUTPUT_DIR, 2)
    if (images.length < 1) {
      console.log('   ⚠️  参考图不足，生成中...')
      const gen = await executor.execute('qwen-2512-t2i', {
        prompt: 'a red apple',
        steps: 4, seed: 10, width: 512, height: 512,
      }, { outputDir: OUTPUT_DIR })
      if (gen.outputs.length > 0) images.push(gen.outputs[0].localPath)
      const gen2 = await executor.execute('qwen-2512-t2i', {
        prompt: 'a green apple',
        steps: 4, seed: 11, width: 512, height: 512,
      }, { outputDir: OUTPUT_DIR })
      if (gen2.outputs.length > 0) images.push(gen2.outputs[0].localPath)
    }

    const inputs: Record<string, string | number | undefined> = {
      scene_prompt: 'a fruit bowl on a table',
      composite_prompt: 'Picture 1 and Picture 2 in a wooden fruit bowl, bright kitchen lighting',
      steps: 4,
      seed: 3,
    }
    if (images.length >= 1) inputs.character_ref_1 = images[0]
    if (images.length >= 2) inputs.character_ref_2 = images[1]

    const result = await executor.execute('qwen-2511-edit-plus', inputs, { outputDir: OUTPUT_DIR })
    console.log(`   status: ${result.status}, duration: ${result.duration}ms, refs: ${images.length}`)
    for (const o of result.outputs) {
      console.log(`     📄 ${o.type}: ${path.basename(o.localPath)}`)
    }
    console.log(result.status === 'success' && result.outputs.length > 0 ? '   ✅ PASS' : '   ❌ FAIL')
  } catch (err) {
    console.error(`   ❌ FAIL: ${err instanceof Error ? err.message : err}`)
  }
  console.log()

  // ════════════════════════════════════════════════
  // Test 4: qwen-2511-edit-multiangle — 多角度
  // ════════════════════════════════════════════════
  console.log('─'.repeat(50))
  console.log('🧪 Test 4: qwen-2511-edit-multiangle — 多角度')
  console.log('─'.repeat(50))
  try {
    const refImage = await findTestImage(OUTPUT_DIR)
    if (refImage) {
      const result = await executor.execute('qwen-2511-edit-multiangle', {
        source_image: refImage,
        prompt: '<sks> right side view eye-level shot medium shot',
        steps: 4,
        seed: 20,
      }, { outputDir: OUTPUT_DIR })
      console.log(`   status: ${result.status}, duration: ${result.duration}ms, outputs: ${result.outputs.length}`)
      for (const o of result.outputs) {
        console.log(`     📄 ${o.type}: ${path.basename(o.localPath)}`)
      }
      console.log(result.status === 'success' && result.outputs.length > 0 ? '   ✅ PASS' : '   ❌ FAIL')
    } else {
      console.log('   ⚠️  无参考图，跳过')
    }
  } catch (err) {
    console.error(`   ❌ FAIL: ${err instanceof Error ? err.message : err}`)
  }
  console.log()

  // ════════════════════════════════════════════════
  // H3 视频测试（条件执行）
  // ════════════════════════════════════════════════
  if (!skipH3) {
    // Test 5: h3-t2v — 文生视频
    console.log('─'.repeat(50))
    console.log('🧪 Test 5: h3-t2v — 文生视频 (约 120s)')
    console.log('─'.repeat(50))
    try {
      const result = await executor.execute('h3-t2v', {
        prompt: 'A calm ocean wave crashing on a sandy beach, cinematic quality',
        steps: 15,
        seed: 30,
        length: 34,  // ~1.4s at 24fps
        width: 544,
        height: 544,
      }, { outputDir: OUTPUT_DIR, timeout: 200_000 })
      console.log(`   status: ${result.status}, duration: ${result.duration}ms, outputs: ${result.outputs.length}`)
      for (const o of result.outputs) {
        const size = fs.statSync(o.localPath).size
        console.log(`     📄 ${o.type}: ${path.basename(o.localPath)} (${(size / 1024 / 1024).toFixed(2)} MB)`)
      }
      console.log(result.status === 'success' && result.outputs.length > 0 ? '   ✅ PASS' : '   ❌ FAIL')
    } catch (err) {
      console.error(`   ❌ FAIL: ${err instanceof Error ? err.message : err}`)
    }
    console.log()

    // Test 6: h3-i2v — 图片转视频
    console.log('─'.repeat(50))
    console.log('🧪 Test 6: h3-i2v — 图片转视频 (约 120s)')
    console.log('─'.repeat(50))
    try {
      const refImage = await findTestImage(OUTPUT_DIR)
      if (refImage) {
        await client.freeMemory()
        const result = await executor.execute('h3-i2v', {
          prompt: 'slow camera pan across the scene, gentle motion',
          first_frame: refImage,
          steps: 15,
          seed: 40,
          length: 34,
          width: 544,
          height: 544,
        }, { outputDir: OUTPUT_DIR, timeout: 200_000 })
        console.log(`   status: ${result.status}, duration: ${result.duration}ms, outputs: ${result.outputs.length}`)
        for (const o of result.outputs) {
          const size = fs.statSync(o.localPath).size
          console.log(`     📄 ${o.type}: ${path.basename(o.localPath)} (${(size / 1024 / 1024).toFixed(2)} MB)`)
        }
        console.log(result.status === 'success' && result.outputs.length > 0 ? '   ✅ PASS' : '   ❌ FAIL')
      } else {
        console.log('   ⚠️  无参考图，跳过')
      }
    } catch (err) {
      console.error(`   ❌ FAIL: ${err instanceof Error ? err.message : err}`)
    }
    console.log()

    // Test 7: h3-r2v — 多参考图转视频
    console.log('─'.repeat(50))
    console.log('🧪 Test 7: h3-r2v — 多参考图转视频 (约 120s)')
    console.log('─'.repeat(50))
    try {
      const refImage = await findTestImage(OUTPUT_DIR)
      if (refImage) {
        await client.freeMemory()
        const result = await executor.execute('h3-r2v', {
          prompt: '<Picture 1> slowly rotating, soft natural lighting',
          ref_image: refImage,
          steps: 15,
          seed: 50,
          length: 34,
          width: 544,
          height: 544,
        }, { outputDir: OUTPUT_DIR, timeout: 200_000 })
        console.log(`   status: ${result.status}, duration: ${result.duration}ms, outputs: ${result.outputs.length}`)
        for (const o of result.outputs) {
          const size = fs.statSync(o.localPath).size
          console.log(`     📄 ${o.type}: ${path.basename(o.localPath)} (${(size / 1024 / 1024).toFixed(2)} MB)`)
        }
        console.log(result.status === 'success' && result.outputs.length > 0 ? '   ✅ PASS' : '   ❌ FAIL')
      } else {
        console.log('   ⚠️  无参考图，跳过')
      }
    } catch (err) {
      console.error(`   ❌ FAIL: ${err instanceof Error ? err.message : err}`)
    }
    console.log()
  } else {
    console.log('⏭️  跳过 H3 视频测试 (--skip-h3)')
    console.log()
  }

  // ── Summary ──
  console.log('='.repeat(60))
  console.log('📊 测试完成')
  const sizes = getOutputSizes(OUTPUT_DIR)
  console.log(`  总文件: ${sizes.count}`)
  console.log(`  总大小: ${(sizes.totalBytes / 1024 / 1024).toFixed(2)} MB`)
  console.log(`  目录: ${OUTPUT_DIR}`)
  console.log('='.repeat(60))
}

// ── Helpers ──

/** Find the first test image in the output directory */
async function findTestImage(dir: string): Promise<string | undefined> {
  if (!fs.existsSync(dir)) return undefined
  const files = fs.readdirSync(dir, { recursive: true })
  for (const f of files) {
    const fullPath = path.join(dir, f.toString())
    if (fs.statSync(fullPath).isFile() && /\.(png|jpg|jpeg|webp)$/i.test(fullPath)) {
      return fullPath
    }
  }
  return undefined
}

/** Collect N image paths from output directory */
async function collectImages(dir: string, n: number): Promise<string[]> {
  const result: string[] = []
  if (!fs.existsSync(dir)) return result
  const files = fs.readdirSync(dir, { recursive: true })
  for (const f of files) {
    const fullPath = path.join(dir, f.toString())
    if (fs.statSync(fullPath).isFile() && /\.(png|jpg|jpeg|webp)$/i.test(fullPath)) {
      result.push(fullPath)
      if (result.length >= n) break
    }
  }
  return result
}

function getOutputSizes(dir: string): { count: number; totalBytes: number } {
  let count = 0
  let totalBytes = 0
  if (!fs.existsSync(dir)) return { count, totalBytes }
  for (const f of fs.readdirSync(dir, { recursive: true })) {
    const fullPath = path.join(dir, f.toString())
    if (fs.statSync(fullPath).isFile()) {
      count++
      totalBytes += fs.statSync(fullPath).size
    }
  }
  return { count, totalBytes }
}

main().catch(err => {
  console.error('FATAL:', err)
  process.exit(1)
})