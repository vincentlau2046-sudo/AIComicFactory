# AIComicBuilder 数据库 Schema 审计报告

> 分析日期: 2026-08-06
> 源码: `src/lib/db/schema.ts` + `drizzle/` 迁移文件
> ORM: Drizzle ORM (SQLite / better-sqlite3)
> 迁移策略: `drizzle-kit` 迁移, 含 baseline 机制

---

## 1. 全部表定义 (共 19 张表)

### 1.1 projects (项目)

| 字段 | 类型 | 约束 | 默认值 |
|------|------|------|--------|
| `id` | text | PK | — |
| `user_id` | text | NOT NULL | `""` |
| `title` | text | NOT NULL | — |
| `idea` | text | — | `""` |
| `script` | text | — | `""` |
| `outline` | text | — | `""` |
| `status` | text (enum) | NOT NULL | `"draft"` |
| `final_video_url` | text | — | — |
| `generation_mode` | text (enum) | NOT NULL | `"keyframe"` |
| `use_project_prompts` | integer | NOT NULL | `0` |
| `color_palette` | text | — | `""` |
| `world_setting` | text | — | `""` |
| `target_duration` | integer | — | `0` |
| `bgm_url` | text | — | `""` |
| `created_at` | integer (timestamp) | NOT NULL | `$defaultFn(() => new Date())` |
| `updated_at` | integer (timestamp) | NOT NULL | `$defaultFn(() => new Date())` |

**索引**: `projects_user_id_idx` ON `user_id` (来自 0001)

**外键**: 无

---

### 1.2 episodes (集)

| 字段 | 类型 | 约束 | 默认值 |
|------|------|------|--------|
| `id` | text | PK | — |
| `project_id` | text | NOT NULL, FK→projects(id) ON DELETE CASCADE | — |
| `title` | text | NOT NULL | — |
| `sequence` | integer | NOT NULL | — |
| `idea` | text | — | `""` |
| `script` | text | — | `""` |
| `outline` | text | — | `""` |
| `status` | text (enum) | NOT NULL | `"draft"` |
| `generation_mode` | text (enum) | NOT NULL | `"keyframe"` |
| `description` | text | — | `""` |
| `keywords` | text | — | `""` |
| `script_hash` | text | — | `""` |
| `color_palette` | text | — | `""` |
| `target_duration` | integer | — | `0` |
| `bgm_url` | text | — | `""` |
| `final_video_url` | text | — | — |
| `created_at` | integer (timestamp) | NOT NULL | `$defaultFn` |
| `updated_at` | integer (timestamp) | NOT NULL | `$defaultFn` |

**索引**: 无显式索引

**外键**: `project_id` → `projects.id` (CASCADE)

---

### 1.3 characters (角色)

| 字段 | 类型 | 约束 | 默认值 |
|------|------|------|--------|
| `id` | text | PK | — |
| `project_id` | text | NOT NULL, FK→projects(id) ON DELETE CASCADE | — |
| `name` | text | NOT NULL | — |
| `description` | text | — | `""` |
| `visual_hint` | text | — | `""` |
| `reference_image` | text | — | — |
| `reference_image_history` | text | — | `"[]"` |
| `scope` | text (enum: main/guest) | NOT NULL | `"main"` |
| `performance_style` | text | — | `""` |
| `height_cm` | integer | — | `0` |
| `body_type` | text | — | `"average"` |
| `is_stale` | integer | NOT NULL | `0` |
| `episode_id` | text | FK→episodes(id) ON DELETE CASCADE | — (nullable) |

**索引**: 无显式索引

**外键**: `project_id` → `projects.id` (CASCADE), `episode_id` → `episodes.id` (CASCADE)

---

### 1.4 episode_characters (集-角色关联)

| 字段 | 类型 | 约束 | 默认值 |
|------|------|------|--------|
| `id` | text | PK | — |
| `episode_id` | text | NOT NULL, FK→episodes(id) ON DELETE CASCADE | — |
| `character_id` | text | NOT NULL, FK→characters(id) ON DELETE CASCADE | — |

**索引**: UNIQUE(`episode_id`, `character_id`) (来自 0013)

**外键**: `episode_id` → `episodes.id` (CASCADE), `character_id` → `characters.id` (CASCADE)

---

### 1.5 storyboard_versions (分镜版本)

| 字段 | 类型 | 约束 | 默认值 |
|------|------|------|--------|
| `id` | text | PK | — |
| `project_id` | text | NOT NULL, FK→projects(id) ON DELETE CASCADE | — |
| `label` | text | NOT NULL | — |
| `version_num` | integer | NOT NULL | — |
| `episode_id` | text | FK→episodes(id) ON DELETE CASCADE | — (nullable) |
| `created_at` | integer (timestamp) | NOT NULL | `$defaultFn` |

**索引**: 无显式索引

**外键**: `project_id` → `projects.id` (CASCADE), `episode_id` → `episodes.id` (CASCADE)

---

### 1.6 scenes (场景)

| 字段 | 类型 | 约束 | 默认值 |
|------|------|------|--------|
| `id` | text | PK | — |
| `episode_id` | text | NOT NULL, FK→episodes(id) ON DELETE CASCADE | — |
| `project_id` | text | NOT NULL, FK→projects(id) ON DELETE CASCADE | — |
| `title` | text | NOT NULL | `""` |
| `description` | text | — | `""` |
| `lighting` | text | — | `""` |
| `color_palette` | text | — | `""` |
| `sequence` | integer | NOT NULL | `0` |
| `created_at` | integer (timestamp) | NOT NULL | `$defaultFn` |

**索引**: 无显式索引

**外键**: `episode_id` → `episodes.id` (CASCADE), `project_id` → `projects.id` (CASCADE)

---

### 1.7 shots (镜头)

| 字段 | 类型 | 约束 | 默认值 |
|------|------|------|--------|
| `id` | text | PK | — |
| `project_id` | text | NOT NULL, FK→projects(id) ON DELETE CASCADE | — |
| `sequence` | integer | NOT NULL | — |
| `prompt` | text | — | `""` |
| `motion_script` | text | — | — |
| `camera_direction` | text | — | `"static"` |
| `duration` | integer | NOT NULL | `10` |
| `video_script` | text | — | — |
| `video_prompt` | text | — | — |
| `transition_in` | text | — | `"cut"` |
| `transition_out` | text | — | `"cut"` |
| `episode_id` | text | FK→episodes(id) ON DELETE CASCADE | — (nullable) |
| `version_id` | text | FK→storyboard_versions(id) ON DELETE CASCADE | — (nullable) |
| `scene_id` | text | — (nullable, 无 FK) | — |
| `composition_guide` | text | — | `""` |
| `focal_point` | text | — | `""` |
| `depth_of_field` | text | — | `"medium"` |
| `sound_design` | text | — | `""` |
| `music_cue` | text | — | `""` |
| `costume_overrides` | text | — | `""` |
| `is_stale` | integer | NOT NULL | `0` |
| `status` | text (enum) | NOT NULL | `"pending"` |

**索引**: 无显式索引

**外键**: `project_id` → `projects.id` (CASCADE), `episode_id` → `episodes.id` (CASCADE), `version_id` → `storyboard_versions.id` (CASCADE)

> ⚠️ `scene_id` 无外键约束 (schema.ts 中未声明 references)

---

### 1.8 shot_assets (镜头资产)

| 字段 | 类型 | 约束 | 默认值 |
|------|------|------|--------|
| `id` | text | PK | — |
| `shot_id` | text | NOT NULL, FK→shots(id) ON DELETE CASCADE | — |
| `type` | text (enum: first_frame/last_frame/reference/keyframe_video/reference_video) | NOT NULL | — |
| `sequence_in_type` | integer | NOT NULL | `0` |
| `asset_version` | integer | NOT NULL | `1` |
| `is_active` | integer | NOT NULL | `1` |
| `prompt` | text | NOT NULL | `""` |
| `file_url` | text | — | — |
| `status` | text (enum: pending/generating/completed/failed) | NOT NULL | `"pending"` |
| `characters` | text | — | — |
| `model_provider` | text | — | — |
| `model_id` | text | — | — |
| `meta` | text | — | — |
| `created_at` | integer (timestamp) | NOT NULL | `$defaultFn` |
| `updated_at` | integer (timestamp) | NOT NULL | `$defaultFn` |

**索引**:
- `idx_shot_assets_shot_type` ON `shot_assets(shot_id, type)`
- `idx_shot_assets_active` ON `shot_assets(shot_id, type, sequence_in_type, is_active)`

**外键**: `shot_id` → `shots.id` (CASCADE)

---

### 1.9 dialogues (对话)

| 字段 | 类型 | 约束 | 默认值 |
|------|------|------|--------|
| `id` | text | PK | — |
| `shot_id` | text | NOT NULL, FK→shots(id) ON DELETE CASCADE | — |
| `character_id` | text | NOT NULL, FK→characters(id) ON DELETE CASCADE | — |
| `text` | text | NOT NULL | — |
| `audio_url` | text | — | — |
| `sequence` | integer | NOT NULL | `0` |
| `start_ratio` | text | — | `"0"` |
| `end_ratio` | text | — | `"1"` |

**索引**: 无显式索引

**外键**: `shot_id` → `shots.id` (CASCADE), `character_id` → `characters.id` (CASCADE)

---

### 1.10 import_logs (导入日志)

| 字段 | 类型 | 约束 | 默认值 |
|------|------|------|--------|
| `id` | text | PK | — |
| `project_id` | text | NOT NULL, FK→projects(id) ON DELETE CASCADE | — |
| `step` | integer | NOT NULL | — |
| `status` | text (enum: running/done/error) | NOT NULL | `"running"` |
| `message` | text | NOT NULL | `""` |
| `metadata` | text (json mode) | — | — |
| `created_at` | integer (timestamp) | NOT NULL | `$defaultFn` |

**索引**: 无显式索引

**外键**: `project_id` → `projects.id` (CASCADE)

---

### 1.11 prompt_templates (提示词模板)

| 字段 | 类型 | 约束 | 默认值 |
|------|------|------|--------|
| `id` | text | PK | — |
| `user_id` | text | NOT NULL | — |
| `prompt_key` | text | NOT NULL | — |
| `slot_key` | text | — | — |
| `scope` | text (enum: global/project) | NOT NULL | `"global"` |
| `project_id` | text | — (nullable) | — |
| `content` | text | NOT NULL | — |
| `created_at` | integer (timestamp) | NOT NULL | `$defaultFn` |
| `updated_at` | integer (timestamp) | NOT NULL | `$defaultFn` |

**索引**:
- UNIQUE(`user_id`, `prompt_key`, `COALESCE(slot_key, '')`, `scope`, `COALESCE(project_id, '')`) — `idx_prompt_templates_unique`
- `idx_prompt_templates_user_scope` ON (`user_id`, `scope`)

**外键**: 无

---

### 1.12 prompt_versions (提示词版本)

| 字段 | 类型 | 约束 | 默认值 |
|------|------|------|--------|
| `id` | text | PK | — |
| `template_id` | text | NOT NULL, FK→prompt_templates(id) ON DELETE CASCADE | — |
| `content` | text | NOT NULL | — |
| `created_at` | integer (timestamp) | NOT NULL | `$defaultFn` |

**索引**: `idx_prompt_versions_template` ON `template_id`

**外键**: `template_id` → `prompt_templates.id` (CASCADE)

---

### 1.13 prompt_presets (提示词预设)

| 字段 | 类型 | 约束 | 默认值 |
|------|------|------|--------|
| `id` | text | PK | — |
| `name` | text | NOT NULL | — |
| `user_id` | text | — (nullable) | — |
| `prompt_key` | text | NOT NULL | — |
| `slots` | text (json mode) | NOT NULL | — |
| `created_at` | integer (timestamp) | NOT NULL | `$defaultFn` |

**索引**: `idx_prompt_presets_user` ON `user_id`

**外键**: 无

---

### 1.14 character_relations (角色关系)

| 字段 | 类型 | 约束 | 默认值 |
|------|------|------|--------|
| `id` | text | PK | — |
| `project_id` | text | NOT NULL, FK→projects(id) ON DELETE CASCADE | — |
| `character_a_id` | text | NOT NULL, FK→characters(id) ON DELETE CASCADE | — |
| `character_b_id` | text | NOT NULL, FK→characters(id) ON DELETE CASCADE | — |
| `relation_type` | text | NOT NULL | `"neutral"` |
| `description` | text | — | `""` |
| `created_at` | integer (timestamp) | NOT NULL | `$defaultFn` |

**索引**: 无显式索引

**外键**: `project_id` → `projects.id` (CASCADE), `character_a_id` → `characters.id` (CASCADE), `character_b_id` → `characters.id` (CASCADE)

---

### 1.15 character_costumes (角色服装)

| 字段 | 类型 | 约束 | 默认值 |
|------|------|------|--------|
| `id` | text | PK | — |
| `character_id` | text | NOT NULL, FK→characters(id) ON DELETE CASCADE | — |
| `name` | text | NOT NULL | `"default"` |
| `description` | text | — | `""` |
| `reference_image` | text | — | — |
| `created_at` | integer (timestamp) | NOT NULL | `$defaultFn` |

**索引**: 无显式索引

**外键**: `character_id` → `characters.id` (CASCADE)

---

### 1.16 mood_board_images (情绪板图片)

| 字段 | 类型 | 约束 | 默认值 |
|------|------|------|--------|
| `id` | text | PK | — |
| `project_id` | text | NOT NULL, FK→projects(id) ON DELETE CASCADE | — |
| `image_url` | text | NOT NULL | — |
| `annotation` | text | — | `""` |
| `extracted_style` | text | — | `""` |
| `created_at` | integer (timestamp) | NOT NULL | `$defaultFn` |

**索引**: 无显式索引

**外键**: `project_id` → `projects.id` (CASCADE)

---

### 1.17 shot_actions (镜头动作)

| 字段 | 类型 | 约束 | 默认值 |
|------|------|------|--------|
| `id` | text | PK | — |
| `shot_id` | text | NOT NULL, FK→shots(id) ON DELETE CASCADE | — |
| `character_id` | text | — (nullable) | — |
| `body_part` | text | — | `"full_body"` |
| `motion` | text | NOT NULL | `""` |
| `start_time` | text | — | `"0"` |
| `end_time` | text | — | `"0"` |
| `intensity` | text | — | `"normal"` |
| `created_at` | integer (timestamp) | NOT NULL | `$defaultFn` |

**索引**: 无显式索引

**外键**: `shot_id` → `shots.id` (CASCADE)

> ⚠️ `character_id` 无外键约束 (nullable, 未声明 references)

---

### 1.18 prompt_ab_tests (提示词 A/B 测试)

| 字段 | 类型 | 约束 | 默认值 |
|------|------|------|--------|
| `id` | text | PK | — |
| `prompt_key` | text | NOT NULL | — |
| `variant_a` | text | NOT NULL | — |
| `variant_b` | text | NOT NULL | — |
| `shot_id` | text | — (nullable) | — |
| `result_a_url` | text | — | — |
| `result_b_url` | text | — | — |
| `preferred` | text | — | — |
| `created_at` | integer (timestamp) | NOT NULL | `$defaultFn` |

**索引**: 无显式索引

**外键**: 无 (包括 `shot_id` 无 FK)

---

### 1.19 tasks (任务)

| 字段 | 类型 | 约束 | 默认值 |
|------|------|------|--------|
| `id` | text | PK | — |
| `project_id` | text | FK→projects(id) ON DELETE CASCADE | — (nullable) |
| `type` | text (enum: 8 种任务类型) | NOT NULL | — |
| `status` | text (enum: pending/running/completed/failed) | NOT NULL | `"pending"` |
| `payload` | text (json mode) | — | — |
| `result` | text (json mode) | — | — |
| `error` | text | — | — |
| `retries` | integer | NOT NULL | `0` |
| `max_retries` | integer | NOT NULL | `3` |
| `created_at` | integer (timestamp) | NOT NULL | `$defaultFn` |
| `scheduled_at` | integer (timestamp) | — | — |
| `episode_id` | text | FK→episodes(id) ON DELETE CASCADE | — (nullable) |

**索引**: 无显式索引

**外键**: `project_id` → `projects.id` (CASCADE), `episode_id` → `episodes.id` (CASCADE)

---

### 1.20 agents (AI Agent)

| 字段 | 类型 | 约束 | 默认值 |
|------|------|------|--------|
| `id` | text | PK | — |
| `user_id` | text | NOT NULL | `""` |
| `name` | text | NOT NULL | — |
| `category` | text (enum: 9 种) | NOT NULL | — |
| `platform` | text (enum: bailian/dify/coze) | NOT NULL | `"bailian"` |
| `app_id` | text | NOT NULL | — |
| `api_key` | text | NOT NULL | — |
| `description` | text | — | `""` |
| `created_at` | integer (timestamp) | NOT NULL | `$defaultFn` |
| `updated_at` | integer (timestamp) | NOT NULL | `$defaultFn` |

**索引**: `idx_agents_user_category` ON (`user_id`, `category`)

**外键**: 无

---

### 1.21 agent_bindings (Agent 绑定)

| 字段 | 类型 | 约束 | 默认值 |
|------|------|------|--------|
| `id` | text | PK | — |
| `project_id` | text | NOT NULL, FK→projects(id) ON DELETE CASCADE | — |
| `category` | text (enum: 9 种) | NOT NULL | — |
| `agent_id` | text | FK→agents(id) ON DELETE SET NULL | — (nullable) |

**索引**: UNIQUE(`project_id`, `category`) (来自 0052)

**外键**: `project_id` → `projects.id` (CASCADE), `agent_id` → `agents.id` (SET NULL)

---

## 2. ER 关系图

```
                                    ┌──────────────┐
                                    │   projects     │
                                    │ PK: id (text)  │
                                    └──────┬───────┘
                                            │
                    ┌───────────────────────┼───────────────────────┐
                    │                       │                       │
              1:Many  ON DELETE CASCADE     │                  Many:1
         ┌───────────────┐              1:Many ON DELETE CASCADE  │
         │  episodes     │              ┌──────────────┐          │
         │ PK: id (text)  │◄────────────│ FK: project_id │         │
         │ FK: project_id │              └──────────────┘          │
         └──┬──────────┬──┘                                        │
            │            │                                          │
         Many:1       Many:1                                      │
            │            │                                          │
         ┌───┴──┐      ┌───┴───────┐                               │
         │      │      │           │                               │
         │    1:Many  Many:1     Many:1                             │
         │       │         │            │                            │
         │    ┌──────┐  ┌────────┐  ┌─────────┐                     │
         │    │ shots │  │scenes │  │storyboard│                     │
         │    │PK:id │  │PK:id │  │_versions │                     │
         │    │FK:ep │  │FK:ep │  │PK:id     │                     │
         │    │FK:prj│  │FK:prj│  │FK:prj    │                     │
         │    └──┬───┘  └──────┘  │FK:ep     │                     │
         │        │              └─────┬─────┘                     │
         │    1:Many                  │                              │
         │       │              Many:1  (nullable)                 │
         │    ┌────────┐             │                              │
         │    │shot_    │◄───────────│                               │
         │    │assets   │  FK:version_id                              │
         │    │PK: id   │                                                │
         │    │FK: shot │                                                │
         │    └────────┘                                                │
         │                                                               │
         │  1:Many                                                     │
         │     │                                                      │
         │  ┌──────┐                                                │
         │  │ dialogues │                                            │
         │  │ PK: id   │                                            │
         │  │ FK: shot │                                            │
         │  │ FK: char │                                            │
         │  └──────┘                                               │
         │                                                          │
         │   1:Many                                                │
         │      │                                                   │
         │  ┌─────────┐                                            │
         │  │ shot_    │                                           │
         │  │ actions  │                                           │
         │  │ PK: id   │                                           │
         │  │ FK: shot │                                           │
         │  └─────────┘                                            │
         │                                                         │
   1:Many │ 1:Many                                                 │
         │     │                                                    │
         └─────┴───────┐                                            │
         characters   │                                             │
         PK: id        │                                             │
         FK: project   │                                             │
         FK: episode?  │                                             │
                       │                                             │
               ┌────────┴─────────┐                                 │
               │                    │                                │
           Many:1               Many:1                                │
               │                    │                                │
         ┌───────┴──────┐      ┌──────┴─────┐                          │
         │character_   │      │ character_  │                          │
         │relations    │      │ costumes    │                          │
         │ PK: id       │      │ PK: id      │                          │
         │ FK: project  │      │ FK: char    │                          │
         │ FK: char A   │      └────────────┘                          │
         │ FK: char B   │                                               │
         └─────────────┘                                                │
               │                                                          │
      Many:1   │                                                           │
               │  1:Many  (via episode_characters)                          │
         ┌──────┴──────┐                                                    │
         │episode_      │                                                    │
         │characters  │  UNIQUE(episode_id, character_id)                   │
         │ PK: id      │  FK: episode_id → episodes                         │
         │ FK: episode │  FK: character_id → characters                      │
         └────────────┘                                                     │
                                                                            │
   其他表 (无 FK 或仅通过 FK 关联 projects):                                │
   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐                   │
   │import_logs   │   │mood_board    │   │ tasks        │                   │
   │ FK: project  │   │_images       │   │ FK: project  │                   │
   └──────────────┘   │ FK: project  │   │ FK: episode  │                   │
                      └──────────────┘   └──────────────┘                   │
   ┌──────────────────┐  ┌──────────────┐  ┌────────────────────┐           │
   │prompt_templates  │  │prompt_       │  │prompt_ab_tests    │           │
   │ (无 FK)          │  │presets        │  │ (无 FK)           │           │
   └──────────────────┘  └──────────────┘  └────────────────────┘           │
   ┌──────────────┐              ┌──────────────┐                            │
   │ agents       │              │agent_bindings│                            │
   │ (无 FK)      │              │ FK: project  │                            │
   └──────────────┘              │ FK: agent    │                            │
                                 └──────────────┘                            │
                                        UNQ(project_id,category)
                                        ON DELETE SET NULL
```

---

## 3. 索引策略分析

### 3.1 现有索引清单

| 索引名 | 表 | 列 | 类型 | 来源迁移 |
|--------|---|---|---|---|
| `projects_user_id_idx` | projects | `user_id` | INDEX | 0001 |
| `idx_prompt_templates_unique` | prompt_templates | `(user_id, prompt_key, COALESCE(slot_key,''), scope, COALESCE(project_id,''))` | UNIQUE INDEX | 0014 |
| `idx_prompt_templates_user_scope` | prompt_templates | `(user_id, scope)` | INDEX | 0014 |
| `idx_prompt_versions_template` | prompt_versions | `template_id` | INDEX | 0014 |
| `idx_prompt_presets_user` | prompt_presets | `user_id` | INDEX | 0014 |
| `idx_shot_assets_shot_type` | shot_assets | `(shot_id, type)` | INDEX | 0050 |
| `idx_shot_assets_active` | shot_assets | `(shot_id, type, sequence_in_type, is_active)` | INDEX | 0050 |
| `idx_agents_user_category` | agents | `(user_id, category)` | INDEX | 0052 |
| — | episode_characters | `(episode_id, character_id)` | UNIQUE (inline) | 0013 |
| — | agent_bindings | `(project_id, category)` | UNIQUE (inline) | 0052 |

### 3.2 索引策略评价

**✅ 做得好的:**
- `shot_assets` 有两组精心设计的复合索引，覆盖了核心查询模式（按 shot+type 查找、按 shot+type+sequence+is_active 排序）
- `prompt_templates` 的 UNIQUE 索引覆盖了业务唯一性约束
- `agents` 的 `(user_id, category)` 复合索引覆盖了查找用户下某类别 agent 的场景
- 关联表 (`episode_characters`, `agent_bindings`) 使用 UNIQUE 约束防止重复

**⚠️ 缺失的索引 (建议):**

| 表 | 建议索引 | 原因 |
|---|---|---|
| `episodes` | `episodes(project_id)` | 按项目查集，无索引需全表扫描 |
| `episodes` | `episodes(project_id, sequence)` | 按项目+顺序查询 |
| `characters` | `characters(project_id)` | 按项目查角色 |
| `scenes` | `scenes(episode_id)` | 按集查场景 |
| `scenes` | `scenes(project_id)` | 按项目查场景 |
| `shots` | `shots(project_id)` | 按项目查镜头 (高频查询) |
| `shots` | `shots(episode_id)` | 按集查镜头 |
| `shots` | `shots(version_id)` | 按分镜版本查镜头 |
| `dialogues` | `dialogues(shot_id)` | 按镜头查对话 |
| `import_logs` | `import_logs(project_id)` | 按项目查日志 |
| `tasks` | `tasks(project_id)` | 按项目查任务 |
| `tasks` | `tasks(status, created_at)` | 按状态+时间查待处理任务 |
| `tasks` | `tasks(episode_id)` | 按集查任务 |
| `character_relations` | `character_relations(project_id)` | 按项目查关系 |
| `character_costumes` | `character_costumes(character_id)` | 按角色查服装 |
| `mood_board_images` | `mood_board_images(project_id)` | 按项目查情绪板 |
| `shot_actions` | `shot_actions(shot_id)` | 按镜头查动作 |
| `storyboard_versions` | `storyboard_versions(project_id)` | 按项目查版本 |
| `storyboard_versions` | `storyboard_versions(episode_id)` | 按集查版本 |

**⚠️ 索引全部定义在 SQL 迁移文件中，而非 schema.ts**

schema.ts 中没有任何 `.index()` 或 `.unique()` 调用。这意味着:
- 索引信息不反映在 Drizzle schema 定义中
- 如果重新 `drizzle-kit generate`，这些索引可能被遗漏
- `agent_bindings` 的 UNIQUE 约束仅在 SQL 迁移中声明，schema.ts 中未反映

---

## 4. Helper / Migration 文件分析

### 4.1 目录结构

```
src/lib/db/
├── index.ts       — DB 连接、迁移运行、工具函数
└── schema.ts      — 全部表定义

drizzle/
├── 0000 ~ 0053.sql   — 54 个迁移文件
└── meta/
    ├── 0000_snapshot.json
    └── _journal.json

drizzle.config.ts  — Drizzle Kit 配置
```

### 4.2 `src/lib/db/index.ts` 关键设计

| 模块 | 说明 |
|------|------|
| **单例缓存** | `globalForDb.sqlite` / `globalForDb.drizzleDB` 缓存连接，生产环境不缓存（避免 Worker 间共享） |
| **Lazy Proxy** | `db` 导出为 Proxy，首次访问属性时才创建连接 |
| **WAL 模式** | `PRAGMA journal_mode = WAL` — 提升并发读性能 |
| **外键启用** | `PRAGMA foreign_keys = ON` — 显式启用 FK 约束 |
| **路径解析** | `DATABASE_URL` 环境变量 → 默认 `./data/aicomic.db` |
| **Baseline 机制** | 检测到已有 schema 但无迁移记录时，自动读取所有迁移文件并写入 `__drizzle_migrations` |
| **动态 require** | `better-sqlite3`、`drizzle-orm/migrator` 使用动态 require 避免构建时加载原生模块 |

### 4.3 迁移统计

| 指标 | 值 |
|------|---|
| 总迁移数 | 54 (0000 ~ 0053) |
| 初始建表 | 0000 (projects, characters, shots, dialogues, tasks) |
| 最后迁移 | 0053 (agents.platform 枚举扩展) |
| 包含数据回填的迁移 | 0010 (episodes 建表+回填 shots/characters/storyboard_versions/tasks) |
| 包含删除列的迁移 | 0051 (删除 shots 表的 8 个废弃列) |
| 版本跃迁 | 0052 从 v6 → v7 (breakpoints: true) |

### 4.4 `src/app/lib/db/` 目录

**不存在。** 项目中没有 `src/app/lib/db/` 目录。所有 DB 相关代码集中在 `src/lib/db/`。

---

## 5. SQLite 本地化风险评估

### 5.1 高风险 (迁移至其他 RDBMS 需改动)

| 风险点 | 影响 | 说明 |
|--------|------|------|
| **所有主键为 `text`** | 🔴 高 | SQLite 无自增整数 PK 约定, 全库使用 text PK (UUID 风格). 迁移 PG/MySQL 无问题, 但无法利用 `SERIAL`/`AUTO_INCREMENT` |
| **`mode: "json"` 字段** | 🔴 高 | `tasks.payload`, `tasks.result`, `import_logs.metadata`, `prompt_presets.slots` 使用 Drizzle 的 json mode. SQLite 中原样存为 text; PG 需 `JSONB`, MySQL 需 `JSON` |
| **`mode: "timestamp"` 整数** | 🟡 中 | `created_at`/`updated_at` 存为 Unix 毫秒整数. PG 建议 `TIMESTAMPTZ`, MySQL 建议 `DATETIME(3)` |
| **布尔值用 integer** | 🟡 中 | `is_stale`, `is_active`, `use_project_prompts` 用 `0/1` 整数. PG/MySQL 原生支持 `BOOLEAN`, 但 `0/1` 也兼容 |
| **无 CHECK 约束** | 🟢 低 | schema.ts 中未使用 `.check()`. 部分迁移 SQL 中有 (如 `characters.scope`), 但 schema.ts 未声明 |
| **enum 用 text** | 🟡 中 | SQLite 无原生 enum, 用 text + 应用层校验. PG 有原生 `ENUM` 类型, 迁移时可选择升级 |
| **`COALESCE` 在唯一索引中** | 🟡 中 | `idx_prompt_templates_unique` 使用 `COALESCE(slot_key, '')` 和 `COALESCE(project_id, '')`. PG 支持, MySQL 部分版本有差异 |

### 5.2 中风险 (需验证)

| 风险点 | 影响 | 说明 |
|--------|------|------|
| **FK `ON DELETE SET NULL`** | 🟡 | `agent_bindings.agent_id` 使用 `SET NULL`. SQLite 和 PG/MySQL 均支持, 但需注意 nullable 列的默认值 |
| **无 `ON UPDATE` 行为** | 🟢 | 所有 FK 均为 `ON UPDATE no action`. 若迁移后需级联更新 PK (如改为 UUID v7), 无需改动 |
| **`INTEGER` 作为 timestamp** | 🟡 | `$defaultFn(() => new Date())` 在 SQLite 中存储为毫秒级整数. PG 需确认 Drizzle 的 `mode: "timestamp"` 在 `pg` dialect 下的行为 (存为毫秒 bigint 或 `timestamptz`) |
| **`PRAGMA` 设置** | 🟢 | `journal_mode = WAL` 和 `foreign_keys = ON` 是 SQLite 特有. PG/MySQL 无需等价设置 |

### 5.3 低风险

| 风险点 | 影响 | 说明 |
|--------|------|------|
| **Drizzle 单 dialect** | 🟢 | 当前仅使用 `drizzle-orm/sqlite-core`. 迁移需切换到 `pg-core` 或 `mysql-core`, schema.ts 需改 `sqliteTable` → `pgTable`/`mysqlTable` |
| **`$defaultFn`** | 🟢 | Drizzle 的 JS 默认值在 SQLite 中由应用层注入. PG 可用 `default: () => 'now()'` 或 `dbGenerated` 替代 |

### 5.4 迁移成本估算

| 目标 DB | 预估工作量 | 主要变更 |
|---------|-----------|----------|
| **PostgreSQL** | 中 (2-3 天) | `sqliteTable`→`pgTable`, `text` PK 保留, `mode: "json"` 需验证, timestamp 需确认精度, 枚举可用 PG 原生 enum |
| **MySQL** | 中 (2-3 天) | `sqliteTable`→`mysqlTable`, `mode: "json"` → MySQL `JSON`, 布尔值可保持 integer, timestamp 用 `DATETIME(3)` |

---

## 6. 总结与建议

### 6.1 Schema 设计评价

| 维度 | 评分 | 说明 |
|------|------|------|
| **规范化** | ★★★★ | 以 projects 为根, episodes 为中间层, shots/dialogues/assets 为叶子, 层次清晰 |
| **完整性** | ★★★☆ | 大部分 FK 声明完整, 但 `shots.scene_id`、`shot_actions.character_id`、`prompt_ab_tests.shot_id` 缺少 FK |
| **索引覆盖** | ★★☆ | 仅 8 个索引 + 2 个 UNIQUE. 大量高频查询路径无索引 (episodes/characters/shots 按 project_id 查询) |
| **可维护性** | ★★★★ | 54 个细粒度迁移, baseline 机制完善, schema.ts 单一文件管理 |
| **版本管理** | ★★★☆ | 索引不在 schema.ts 中声明, 依赖手动迁移 SQL, 有漂移风险 |

### 6.2 优先建议

1. **补充缺失索引** — `episodes(project_id)`, `characters(project_id)`, `shots(project_id)`, `shots(episode_id)` 是最关键的 4 个
2. **schema.ts 中声明索引** — 使用 `.index()` 和 `.unique()` 方法, 确保 schema 与迁移一致
3. **补全外键** — `shots.scene_id` → `scenes`, `shot_actions.character_id` → `characters`, `prompt_ab_tests.shot_id` → `shots`
4. **考虑 `sequence` 字段的约束** — `episodes.sequence`、`shots.sequence`、`scenes.sequence` 建议加 UNIQUE(project_id/episode_id, sequence) 防止重复序号
