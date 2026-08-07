# AtomCode Pipeline Engine Review — 汇总分析

## Review 覆盖

| Chunk | 文件 | 发现数 | HIGH | MED | LOW |
|-------|------|--------|------|-----|-----|
| types | types.ts | 9 | 3 | 4 | 2 |
| template | template.ts | 10 | 0 | 6 | 4 |
| gpu-scheduler | gpu-scheduler.ts | 5 | 1 | 3 | 1 |
| loader | loader.ts | 12 | 2 | 5 | 5 |
| atomic-step | steps/atomic.ts | 10 | 3 | 3 | 4 |
| script-step | steps/script.ts | 6 | 2 | 3 | 1 |
| executor | executor.ts | 7 | 2 | 3 | 2 |
| pipeline-engine | index.ts | 7 | 0 | 4 | 3 |
| provider-integration | provider.ts + setup.ts | 7 | 1 | 3 | 3 |
| pipeline-yamls | *.yaml | 6 | 2 | 2 | 2 |
| test-file | test-pipeline-engine.ts | 6 | 2 | 3 | 1 |
| **合计** | | **85** | **16** | **39** | **28** |

---

## 🔴 HIGH 严重度 — 必须修复（16 项，去重后 12 个独立问题）

### A. 运行时正确性 Bug（5 项）

| # | 来源 | 问题 | 影响 |
|---|------|------|------|
| H1 | atomic-step | `step.outputs` 模板从未解析，所有 named output 硬编码为 `outputs[0]` | 多输出工作流命名映射错误 |
| H2 | atomic-step | executor `status:'timeout'` 被忽略，超时步骤报告为成功 | 超时不触发重试，静默产出空结果 |
| H3 | script-step | `readdirSync` 顺序不稳定 → named output 映射不确定 | 同一脚本不同运行产生不同输出名 |
| H4 | pipeline-yamls | `${params.seed + 1}` 算术表达式不被模板解析器支持 | character-image 的 seed 增量全部失效 |
| H5 | pipeline-yamls | `${params.referenceImages[0]}` 数组索引不被支持 | frame-generate 的参考图输入全部为 null |

### B. 类型/承诺与实现不一致（4 项）

| # | 来源 | 问题 | 影响 |
|---|------|------|------|
| H6 | types+executor | `Fallback.action` 声明 4 种但只实现 `skip`，其余 → deadlock | YAML 作者写了 abort/retry 却得到误导性 deadlock 错误 |
| H7 | types+atomic | `RetryPolicy`/`StepRetryExceeded` 声明但从未使用，重试静默无效 | pipeline YAML 中的 retry 配置是死代码 |
| H8 | atomic | 重试耗尽后抛 raw error，不走 StepExecutionError/StepRetryExceeded | 下游无法区分步骤失败类型 |
| H9 | types | 未知 `gpu_model` 静默归为 `'cpu'`，可跳过 freeMemory → GPU OOM | 打字错误或新增模型导致 VRAM 泄漏 |

### C. 安全问题（2 项）

| # | 来源 | 问题 | 影响 |
|---|------|------|------|
| H10 | script-step | `execSync(\`which "${name}"\`)` shell 注入 | pipeline YAML 可执行任意命令 |
| H11 | provider+setup | `setDefaultAIProvider(ComfyUI)` 覆盖文本 provider | 启用 ComfyUI 后 generateText() 全局崩溃 |

---

## 🟡 MEDIUM — 应修复（39 项，归类后 15 个主题）

| 主题 | 来源 | 概要 |
|------|------|------|
| M1: intermediates 死配置 | types+executor | `outputs.intermediates` 声明但运行时忽略 |
| M2: Error.cause 未传入 super() | types | PipelineError 不传 cause 给 Error 构造器 |
| M3: 缺 PipelineNotFoundError/ConfigError | types+loader | loader 抛 bare Error，不可区分 |
| M4: MODEL_FAMILY 可变导出 + 精确匹配 | types | 可被外部修改，前缀匹配更安全 |
| M5: GPU finalize 不在 finally 块 | gpu-scheduler | 异常路径跳过 finalize → VRAM 泄漏 |
| M6: freeMemory 失败不应阻断流程 | gpu-scheduler | free 失败丢掉已完成的结果 |
| M7: GPU 调度器无并发保护 | gpu-scheduler | 共享实例跨 pipeline 竞态 |
| M8: 参数数组索引不支持 | template | `${params.referenceImages[0]}` 返回 null |
| M9: 缺失引用静默失败 | template | `${steps.typo...}` → '' 而非报错 |
| M10: 数值类型未验证 | loader | count/retry.max 接受 NaN |
| M11: fallback.action 未验证 | loader | 无效 action 静默通过 |
| M12: 并发 pipeline 时 execSync 阻塞事件循环 | script-step | 5 分钟阻塞整个 Node 进程 |
| M13: PipelineEngine.pipelinesDir 死配置 | index | 构造器接收但未使用 |
| M14: initialized 在 pipeline 加载前设为 true | provider | 加载失败不可重试 |
| M15: DAG 部分失败丢失已完成步骤输出 | executor | required step 失败时之前产出全部丢失 |

---

## 🟢 LOW — 可延后（28 项，略）

---

## 修复优先级排序

### P0 — 本轮必须修（运行时正确性 + 安全）

1. **H1: atomic-step named outputs 解析** — 接入 `resolveOutputPaths()`
2. **H2: executor timeout 状态检查** — `result.status !== 'success'` 时重试/报错
3. **H3: script-step readdir 排序** — 加 `.sort()`
4. **H4+H5: 模板解析器增强** — 支持 `${params.seed + 1}` 和 `${params.arr[0]}`
5. **H9: gpu_model 未知时 fail-safe** — 默认 `'unknown'` 而非 `'cpu'`
6. **H10: shell 注入** — `execFileSync('which', [name])`
7. **H11: setup.ts provider 覆盖** — 分离 image/video provider 注册

### P1 — 本轮应修（类型/行为一致性）

8. **H6: 缩减 Fallback.action 到 `'skip' | 'abort'`** — 或实现 abort
9. **H7: 实现 retry 循环** — atomic.ts 和 script.ts 中加入重试逻辑
10. **H8: 重试耗尽抛 StepRetryExceeded** — 附带 cause
11. **M2: Error.cause 传入 super()** — `super(message, { cause })`
12. **M5: GPU finalize 移入 finally 块**
13. **M6: freeMemory try/catch + warn**

### P2 — 后续版本

14. M1 intermediates 死配置清理
15. M3 错误类层次细化
16. M4 MODEL_FAMILY 前缀匹配 + as const
17. M7-M15 其余 MEDIUM 项