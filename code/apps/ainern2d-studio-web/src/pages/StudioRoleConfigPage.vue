<template>
  <div class="page-grid">
    <NCard :title="t('role.title')">
      <NGrid :cols="3" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Tenant ID"><NInput v-model:value="tenantId" /></NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Project ID"><NInput v-model:value="projectId" /></NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="关键词"><NInput v-model:value="keyword" placeholder="filter" /></NFormItem>
        </NGridItem>
      </NGrid>
      <NButton type="primary" @click="onReloadAll">{{ t('common.refresh') }}</NButton>
    </NCard>

    <NTabs v-model:value="activeTab" type="card" animated>
      <!-- ═══ Tab 1: 职业定义 ═══ -->
      <NTabPane name="roles" :tab="t('role.roles')">
        <NCard>
          <NFormItem>
            <template #label>
              Role 模板
              <NTooltip trigger="hover" placement="right" style="max-width:280px">
                <template #trigger>
                  <NButton quaternary circle size="tiny" style="margin-left:4px">?</NButton>
                </template>
                选择内置岗位模板可自动填充常用配置，之后可手动覆盖各字段。
              </NTooltip>
            </template>
            <NSelect
              v-model:value="selectedTemplate"
              :options="templateOptions"
              placeholder="选择模板后自动填充..."
              clearable
              filterable
              style="width:300px"
              @update:value="onApplyTemplate"
            />
          </NFormItem>

          <NGrid :cols="2" :x-gap="8" :y-gap="8" responsive="screen" item-responsive>
            <NGridItem span="0:2 900:1">
              <NFormItem>
                <template #label>
                  Role ID
                  <NTooltip trigger="hover" placement="right" style="max-width:280px">
                    <template #trigger>
                      <NButton quaternary circle size="tiny" style="margin-left:4px">?</NButton>
                    </template>
                    唯一标识该职业的英文 ID，如 director / art_director。将作为 CreativePolicyStack 的 name 存储。
                  </NTooltip>
                </template>
                <NInput v-model:value="roleId" />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:2 900:1">
              <NFormItem label="默认模型档案">
                <NSelect v-model:value="roleDefaultModelProfile" :options="modelProfileOptions" clearable filterable />
              </NFormItem>
            </NGridItem>
          </NGrid>

          <NFormItem>
            <template #label>
              提示词风格
              <NTooltip trigger="hover" placement="right" style="max-width:280px">
                <template #trigger>
                  <NButton quaternary circle size="tiny" style="margin-left:4px">?</NButton>
                </template>
                cinematic=电影感叙事 | documentary=纪录片客观 | wuxia=武侠动作 | anime=动漫热血 | noir=黑色幽默 | game=游戏对话
              </NTooltip>
            </template>
            <NSelect
              v-model:value="rolePromptStyleKey"
              :options="promptStyleOptions"
              style="width:200px;margin-right:8px"
              placeholder="选择风格"
              @update:value="val => { rolePromptStyle = val }"
            />
          </NFormItem>
          <NFormItem label="提示词（自定义覆盖）">
            <NInput v-model:value="rolePromptStyle" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" />
          </NFormItem>

          <NFormItem>
            <template #label>
              默认技能套餐
              <NTooltip trigger="hover" placement="right" style="max-width:320px">
                <template #trigger>
                  <NButton quaternary circle size="tiny" style="margin-left:4px">?</NButton>
                </template>
                技能套餐决定该职业默认可调用的 AI 能力链。<br/>
                shot_planner=镜头规划 | dialogue_director=台词导演 | review_gate=质量门控 | i18n_adapter=翻译适配
              </NTooltip>
            </template>
            <NCheckboxGroup v-model:value="roleDefaultSkills" :options="skillCheckboxOptions" />
          </NFormItem>

          <NFormItem>
            <template #label>
              默认知识作用域
              <NTooltip trigger="hover" placement="right" style="max-width:280px">
                <template #trigger>
                  <NButton quaternary circle size="tiny" style="margin-left:4px">?</NButton>
                </template>
                控制该职业默认可访问的知识库范围。director_basic=基础导演KB | project_style=项目风格KB | novel_world=小说世界观KB
              </NTooltip>
            </template>
            <NCheckboxGroup v-model:value="roleDefaultScopes" :options="scopeOptions" />
          </NFormItem>

          <NGrid :cols="4" :x-gap="8" :y-gap="8" responsive="screen" item-responsive>
            <NGridItem span="0:4 900:1">
              <NFormItem>
                <template #label>
                  导入
                  <NTooltip trigger="hover" placement="right">
                    <template #trigger><NButton quaternary circle size="tiny" style="margin-left:4px">?</NButton></template>
                    允许该职业导入外部文档到知识库
                  </NTooltip>
                </template>
                <NSwitch v-model:value="permImport" />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:4 900:1">
              <NFormItem>
                <template #label>
                  发布
                  <NTooltip trigger="hover" placement="right">
                    <template #trigger><NButton quaternary circle size="tiny" style="margin-left:4px">?</NButton></template>
                    允许该职业发布章节任务
                  </NTooltip>
                </template>
                <NSwitch v-model:value="permPublish" />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:4 900:1">
              <NFormItem>
                <template #label>
                  全局KB
                  <NTooltip trigger="hover" placement="right">
                    <template #trigger><NButton quaternary circle size="tiny" style="margin-left:4px">?</NButton></template>
                    允许该职业编辑全局知识库（高权限）
                  </NTooltip>
                </template>
                <NSwitch v-model:value="permEditGlobalKb" />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:4 900:1">
              <NFormItem>
                <template #label>
                  路由管理
                  <NTooltip trigger="hover" placement="right">
                    <template #trigger><NButton quaternary circle size="tiny" style="margin-left:4px">?</NButton></template>
                    允许该职业管理模型路由配置
                  </NTooltip>
                </template>
                <NSwitch v-model:value="permManageRouter" />
              </NFormItem>
            </NGridItem>
          </NGrid>

          <NSpace>
            <NButton type="primary" @click="onUpsertRole">保存 Role</NButton>
            <NButton type="error" :disabled="!roleId" @click="onDeleteRole(roleId)">删除 Role</NButton>
          </NSpace>
          <NDivider />
          <NDataTable :columns="roleColumns" :data="roleProfiles" :pagination="{ pageSize: 6 }" />
        </NCard>
      </NTabPane>

      <!-- ═══ Tab 2: 技能注册 ═══ -->
      <NTabPane name="skills" :tab="t('role.skills')">
        <NCard>
          <NGrid :cols="2" :x-gap="8" :y-gap="8" responsive="screen" item-responsive>
            <NGridItem span="0:2 900:1">
              <NFormItem>
                <template #label>
                  技能 ID
                  <NTooltip trigger="hover" placement="right" style="max-width:280px">
                    <template #trigger><NButton quaternary circle size="tiny" style="margin-left:4px">?</NButton></template>
                    全局唯一技能标识，如 shot_planner / i18n_adapter。也可从列表选择已有技能进行编辑。
                  </NTooltip>
                </template>
                <NInput v-model:value="skillId" placeholder="shot_planner" />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:2 900:1">
              <NFormItem>
                <template #label>
                  UI Renderer
                  <NTooltip trigger="hover" placement="right" style="max-width:280px">
                    <template #trigger><NButton quaternary circle size="tiny" style="margin-left:4px">?</NButton></template>
                    timeline=时间轴面板 | form=表单输入 | table=数据表格 | json-view=JSON查看器 | node-graph=节点图
                  </NTooltip>
                </template>
                <NSelect v-model:value="skillUiRenderer" :options="uiRendererOptions" />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:2 900:1">
              <NFormItem label="默认模型档案">
                <NSelect v-model:value="skillDefaultModelProfile" :options="modelProfileOptions" clearable filterable />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:2 900:1">
              <NFormItem>
                <template #label>
                  Init Template
                  <NTooltip trigger="hover" placement="right" style="max-width:280px">
                    <template #trigger><NButton quaternary circle size="tiny" style="margin-left:4px">?</NButton></template>
                    初始化模板决定该技能首次运行时加载的预设配置，如 director_bootstrap_v1。
                  </NTooltip>
                </template>
                <NSelect v-model:value="skillInitTemplate" :options="initTemplateOptions" clearable filterable />
              </NFormItem>
            </NGridItem>
          </NGrid>

          <NFormItem>
            <template #label>
              工具集
              <NTooltip trigger="hover" placement="right" style="max-width:280px">
                <template #trigger><NButton quaternary circle size="tiny" style="margin-left:4px">?</NButton></template>
                search=知识搜索 | embedding=向量编码 | image=图像生成 | tts=语音合成 | i2v=图转视频 | stt=语音识别 | tool_calling=函数调用
              </NTooltip>
            </template>
            <NCheckboxGroup v-model:value="skillTools" :options="toolOptions" />
          </NFormItem>

          <NFormItem label="知识作用域">
            <NCheckboxGroup v-model:value="skillKnowledgeScopes" :options="scopeOptions" />
          </NFormItem>

          <NFormItem>
            <template #label>
              输入 Schema（JSON）
              <NTooltip trigger="hover" placement="right" style="max-width:280px">
                <template #trigger><NButton quaternary circle size="tiny" style="margin-left:4px">?</NButton></template>
                JSON Schema 格式，描述该技能接收的参数结构。必须是 object 类型。
              </NTooltip>
            </template>
            <NInput v-model:value="skillInputSchemaText" type="textarea" :autosize="{ minRows: 3, maxRows: 8 }" />
          </NFormItem>

          <NFormItem>
            <template #label>
              输出 Schema（JSON）
              <NTooltip trigger="hover" placement="right" style="max-width:280px">
                <template #trigger><NButton quaternary circle size="tiny" style="margin-left:4px">?</NButton></template>
                JSON Schema 格式，描述该技能输出的数据结构。
              </NTooltip>
            </template>
            <NInput v-model:value="skillOutputSchemaText" type="textarea" :autosize="{ minRows: 3, maxRows: 8 }" />
          </NFormItem>

          <NSpace>
            <NButton type="primary" @click="onUpsertSkill">保存 Skill</NButton>
            <NButton type="error" :disabled="!skillId" @click="onDeleteSkill(skillId)">删除 Skill</NButton>
          </NSpace>
          <NDivider />
          <NDataTable :columns="skillColumns" :data="skillRegistryItems" :pagination="{ pageSize: 6 }" />
        </NCard>
      </NTabPane>

      <!-- ═══ Tab 3: 适用范围 ═══ -->
      <NTabPane name="routes" :tab="t('role.scope')">
        <NCard>
          <NGrid :cols="2" :x-gap="8" :y-gap="8" responsive="screen" item-responsive>
            <NGridItem span="0:2 900:1">
              <NFormItem>
                <template #label>
                  Route ID
                  <NTooltip trigger="hover" placement="right" style="max-width:280px">
                    <template #trigger><NButton quaternary circle size="tiny" style="margin-left:4px">?</NButton></template>
                    路由唯一标识，如 route_scene_board。与前端 Vue Router name 对应。
                  </NTooltip>
                </template>
                <NInput v-model:value="routeId" />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:2 900:1">
              <NFormItem label="Path">
                <NInput v-model:value="routePath" placeholder="/studio/xxx" />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:2 900:1">
              <NFormItem label="Component">
                <NInput v-model:value="routeComponent" />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:2 900:1">
              <NFormItem label="Feature ID">
                <NInput v-model:value="routeFeatureId" />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:2 900:1">
              <NFormItem>
                <template #label>
                  UI Mode
                  <NTooltip trigger="hover" placement="right">
                    <template #trigger><NButton quaternary circle size="tiny" style="margin-left:4px">?</NButton></template>
                    list=列表页 | edit=编辑页 | timeline=时间轴 | config=配置面板
                  </NTooltip>
                </template>
                <NInput v-model:value="routeUiMode" placeholder="list/edit/timeline/config" />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:2 900:1">
              <NFormItem label="Depends On（CSV）">
                <NInput v-model:value="routeDependsOnCsv" placeholder="rag,embedding,minio" />
              </NFormItem>
            </NGridItem>
          </NGrid>
          <NFormItem>
            <template #label>
              允许职业（CSV）
              <NTooltip trigger="hover" placement="right" style="max-width:280px">
                <template #trigger><NButton quaternary circle size="tiny" style="margin-left:4px">?</NButton></template>
                填写允许访问该路由的职业 ID，多个以逗号分隔。如：director,translator。viewer/editor/admin 为平台内置级别。
              </NTooltip>
            </template>
            <NInput v-model:value="routeAllowedRolesCsv" placeholder="director,translator" />
          </NFormItem>
          <NSpace>
            <NButton type="primary" @click="onUpsertRoute">保存 Route</NButton>
            <NButton type="error" :disabled="!routeId" @click="onDeleteRoute(routeId)">删除 Route</NButton>
          </NSpace>
          <NDivider />
          <NDataTable :columns="routeColumns" :data="featureRoutes" :pagination="{ pageSize: 6 }" />
        </NCard>
      </NTabPane>

      <!-- ═══ Tab 4: 预览测试 ═══ -->
      <NTabPane name="preview" :tab="t('role.preview')">
        <NCard>
          <NAlert type="warning" :show-icon="true" style="margin-bottom:12px">
            <NTooltip trigger="hover">
              <template #trigger>⚠️ 预览测试将消耗 LLM token，请谨慎使用。</template>
              每次预览会向配置的模型发送请求，按 token 计费。
            </NTooltip>
          </NAlert>
          <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
            <NGridItem span="0:2 900:1">
              <NFormItem label="选择 Role">
                <NSelect
                  v-model:value="previewRoleId"
                  :options="roleProfiles.map(r => ({ label: r.role_id, value: r.role_id }))"
                  placeholder="选择职业"
                  filterable
                />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:2 900:1">
              <NFormItem label="选择 Skill">
                <NSelect
                  v-model:value="previewSkillId"
                  :options="skillRegistryItems.map(s => ({ label: s.skill_id, value: s.skill_id }))"
                  placeholder="选择技能"
                  filterable
                />
              </NFormItem>
            </NGridItem>
          </NGrid>
          <NText depth="3" style="display:block;margin-bottom:8px">
            选择 Role + Skill 后，点击"解析上下文"将显示该组合的模型、工具、KB 配置预览。
          </NText>
          <NSpace>
            <NButton type="primary" :disabled="!previewRoleId || !previewSkillId" @click="onResolvePreview">
              解析上下文
            </NButton>
          </NSpace>
          <pre v-if="previewResult" class="json-panel" style="margin-top:12px">{{ previewResult }}</pre>
        </NCard>
      </NTabPane>

      <!-- ═══ Tab 5: 职业 KB 绑定 ═══ -->
      <NTabPane name="kb" tab="📚 职业KB">
        <NCard>
          <div style="margin-bottom:12px">
            <NText depth="3" style="font-size:13px">
              职业基座知识库：任何该职业的 Persona 都会继承这些 KB（优先级越大越优先加载）。
            </NText>
          </div>
          <NSpace style="margin-bottom:12px" align="center">
            <NSelect
              v-model:value="kbBindRoleId"
              :options="roleProfiles.map(r => ({ label: r.role_id, value: r.role_id }))"
              placeholder="选择职业"
              filterable
              style="width:200px"
              @update:value="onLoadRoleKBBindings"
            />
            <NButton type="primary" size="small" :disabled="!kbBindRoleId" @click="showKBPickerModal = true">
              + 从资产池选择 KBPack
            </NButton>
          </NSpace>

          <NDataTable
            :columns="roleKBColumns"
            :data="roleKBBindings"
            size="small"
            :pagination="{ pageSize: 8 }"
          />
        </NCard>
      </NTabPane>
    </NTabs>

    <!-- KBPack 选择 Modal -->
    <NModal v-model:show="showKBPickerModal" preset="card" title="从资产池选择 KBPack" style="max-width:600px">
      <NInput v-model:value="kbPickerKeyword" placeholder="🔍 搜索知识包" clearable style="margin-bottom:10px" />
      <NDataTable
        :columns="kbPickerColumns"
        :data="filteredKBPacks"
        size="small"
        :pagination="{ pageSize: 6 }"
      />
    </NModal>

    <NAlert v-if="message" type="success" :show-icon="true">{{ message }}</NAlert>
    <NAlert v-if="errorMessage" type="error" :show-icon="true">{{ errorMessage }}</NAlert>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref, watch } from "vue";
import {
  NAlert,
  NButton,
  NCard,
  NCheckboxGroup,
  NDataTable,
  NDivider,
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NSelect,
  NSpace,
  NSwitch,
  NTabPane,
  NTabs,
  NText,
  NTooltip,
  type DataTableColumns,
} from "naive-ui";
import { useI18n } from "@/composables/useI18n";


import {
  deleteFeatureRouteMap,
  deleteRoleProfile,
  deleteSkillRegistry,
  listFeatureRouteMaps,
  listKBPacks,
  listModelProfiles,
  listRoleKBBindings,
  listRoleProfiles,
  listSkillRegistry,
  createRoleKBBinding,
  deleteRoleKBBinding,
  updateRoleKBBinding,
  upsertFeatureRouteMap,
  upsertRoleProfile,
  upsertSkillRegistry,
  type FeatureRouteMapResponse,
  type KBMapEntry,
  type KBPackResponse,
  type ModelProfileResponse,
  type RoleProfileResponse,
  type SkillRegistryResponse,
} from "@/api/product";

// ─── Role Templates ───────────────────────────────────────────────────────────
interface RoleTemplate {
  id: string;
  label: string;
  promptStyle: string;
  skills: string[];
  scopes: string[];
}

const ROLE_TEMPLATES: RoleTemplate[] = [
  { id: "director",           label: "导演",       promptStyle: "cinematic",    skills: ["shot_planner","dialogue_director","review_gate"],         scopes: ["director_basic","project_style"] },
  { id: "art_director",       label: "美术指导",   promptStyle: "wuxia",        skills: ["style_referee","culture_enforcer"],                       scopes: ["visual_grammar","culture_pack"] },
  { id: "dop",                label: "摄影指导",   promptStyle: "cinematic",    skills: ["camera_planner","lighting_advisor"],                      scopes: ["director_basic","visual_grammar"] },
  { id: "stunt_coordinator",  label: "武术指导",   promptStyle: "wuxia",        skills: ["action_choreographer"],                                   scopes: ["wuxia_action","director_basic"] },
  { id: "script_supervisor",  label: "剧本督导",   promptStyle: "documentary",  skills: ["continuity_checker"],                                     scopes: ["novel_world","project_style"] },
  { id: "translator",         label: "翻译",       promptStyle: "documentary",  skills: ["i18n_adapter"],                                           scopes: ["director_basic","novel_world"] },
  { id: "voice_director",     label: "配音导演",   promptStyle: "cinematic",    skills: ["tts_director"],                                           scopes: ["director_basic"] },
  { id: "sound_designer",     label: "音效设计",   promptStyle: "documentary",  skills: ["sfx_planner"],                                            scopes: ["director_basic"] },
  { id: "vfx_supervisor",     label: "视效监督",   promptStyle: "cinematic",    skills: ["vfx_planner"],                                            scopes: ["director_basic","visual_grammar"] },
  { id: "editor",             label: "剪辑师",     promptStyle: "cinematic",    skills: ["timeline_editor"],                                        scopes: ["director_basic"] },
  { id: "colorist",           label: "调色师",     promptStyle: "cinematic",    skills: ["color_grader"],                                           scopes: ["visual_grammar"] },
  { id: "producer",           label: "制片人",     promptStyle: "documentary",  skills: ["budget_tracker"],                                         scopes: ["director_basic","novel_world"] },
  { id: "casting_director",   label: "选角导演",   promptStyle: "documentary",  skills: ["casting_advisor"],                                        scopes: ["novel_world","director_basic"] },
  { id: "prop_master",        label: "道具师",     promptStyle: "documentary",  skills: ["prop_planner"],                                           scopes: ["novel_world","culture_pack"] },
  { id: "costume_designer",   label: "服装设计",   promptStyle: "wuxia",        skills: ["costume_planner"],                                        scopes: ["culture_pack","visual_grammar"] },
  { id: "makeup_artist",      label: "化妆师",     promptStyle: "documentary",  skills: ["makeup_planner"],                                         scopes: ["culture_pack"] },
  { id: "set_designer",       label: "场景设计",   promptStyle: "cinematic",    skills: ["set_planner"],                                            scopes: ["visual_grammar","culture_pack"] },
  { id: "storyboard_artist",  label: "分镜师",     promptStyle: "anime",        skills: ["storyboard_planner"],                                     scopes: ["director_basic","visual_grammar"] },
  { id: "concept_artist",     label: "概念设计师", promptStyle: "game",         skills: ["concept_planner"],                                        scopes: ["visual_grammar","culture_pack"] },
  { id: "music_director",     label: "音乐总监",   promptStyle: "cinematic",    skills: ["bgm_planner"],                                            scopes: ["director_basic"] },
  { id: "narrator",           label: "旁白",       promptStyle: "documentary",  skills: ["narration_writer"],                                       scopes: ["novel_world","director_basic"] },
  { id: "dialogue_writer",    label: "台词作家",   promptStyle: "cinematic",    skills: ["dialogue_director"],                                      scopes: ["novel_world","project_style"] },
  { id: "action_director",    label: "动作导演",   promptStyle: "anime",        skills: ["action_choreographer","shot_planner"],                    scopes: ["wuxia_action","director_basic"] },
  { id: "post_supervisor",    label: "后期监督",   promptStyle: "documentary",  skills: ["review_gate","timeline_editor"],                          scopes: ["director_basic"] },
  { id: "qa_reviewer",        label: "质量审核",   promptStyle: "documentary",  skills: ["review_gate","continuity_checker"],                       scopes: ["director_basic","novel_world"] },
  { id: "localization_lead",  label: "本地化主管", promptStyle: "documentary",  skills: ["i18n_adapter"],                                           scopes: ["director_basic","culture_pack"] },
  { id: "ai_supervisor",      label: "AI 监督",    promptStyle: "documentary",  skills: ["shot_planner","review_gate","continuity_checker"],        scopes: ["director_basic","novel_world"] },
  { id: "technical_director", label: "技术总监",   promptStyle: "documentary",  skills: ["vfx_planner","sfx_planner","timeline_editor"],            scopes: ["director_basic"] },
  { id: "executive_producer", label: "执行制片",   promptStyle: "documentary",  skills: ["budget_tracker","review_gate"],                           scopes: ["director_basic","novel_world"] },
  { id: "creative_director",  label: "创意总监",   promptStyle: "cinematic",    skills: ["shot_planner","style_referee","dialogue_director"],        scopes: ["director_basic","visual_grammar","project_style"] },
];

const templateOptions = ROLE_TEMPLATES.map(t => ({ label: `${t.label} (${t.id})`, value: t.id }));

// ─── Static Options ───────────────────────────────────────────────────────────
const promptStyleOptions = [
  { label: "cinematic（电影感）", value: "cinematic, decisive, output structured checklist" },
  { label: "documentary（纪录片）", value: "documentary, objective, factual analysis" },
  { label: "wuxia（武侠）", value: "wuxia, dynamic, action-focused cinematic" },
  { label: "anime（动漫）", value: "anime, expressive, high-energy dramatic" },
  { label: "game（游戏）", value: "game, interactive, dialogue-rich" },
  { label: "noir（黑色）", value: "noir, atmospheric, moody psychological" },
];

const scopeOptions = [
  { label: "director_basic", value: "director_basic" },
  { label: "project_style", value: "project_style" },
  { label: "novel_world", value: "novel_world" },
  { label: "visual_grammar", value: "visual_grammar" },
  { label: "culture_pack", value: "culture_pack" },
  { label: "wuxia_action", value: "wuxia_action" },
];

const toolOptions = [
  { label: "search（知识搜索）", value: "search" },
  { label: "embedding（向量编码）", value: "embedding" },
  { label: "image（图像生成）", value: "image" },
  { label: "tts（语音合成）", value: "tts" },
  { label: "i2v（图转视频）", value: "i2v" },
  { label: "stt（语音识别）", value: "stt" },
  { label: "tool_calling（函数调用）", value: "tool_calling" },
];

const uiRendererOptions = [
  { label: "timeline（时间轴）", value: "timeline" },
  { label: "form（表单）", value: "form" },
  { label: "table（数据表格）", value: "table" },
  { label: "json-view（JSON查看器）", value: "json-view" },
  { label: "node-graph（节点图）", value: "node-graph" },
];

const initTemplateOptions = [
  { label: "director_bootstrap_v1", value: "director_bootstrap_v1" },
  { label: "visual_grammar_v1", value: "visual_grammar_v1" },
  { label: "wuxia_style_v1", value: "wuxia_style_v1" },
  { label: "i18n_pack_v1", value: "i18n_pack_v1" },
  { label: "culture_enforcer_v1", value: "culture_enforcer_v1" },
];

// ─── State ────────────────────────────────────────────────────────────────────
const { t } = useI18n();

const tenantId = ref("default");
const projectId = ref("default");
const keyword = ref("");
const activeTab = ref("roles");

const modelProfiles = ref<ModelProfileResponse[]>([]);
const roleProfiles = ref<RoleProfileResponse[]>([]);
const skillRegistryItems = ref<SkillRegistryResponse[]>([]);
const featureRoutes = ref<FeatureRouteMapResponse[]>([]);

// Role tab state
const selectedTemplate = ref<string | null>(null);
const roleId = ref("director");
const rolePromptStyle = ref("cinematic, decisive, output structured checklist");
const rolePromptStyleKey = ref<string | null>(null);
const roleDefaultSkills = ref<string[]>(["shot_planner", "dialogue_director", "review_gate"]);
const roleDefaultScopes = ref<string[]>(["director_basic", "project_style"]);
const roleDefaultModelProfile = ref<string | null>(null);
const permImport = ref(true);
const permPublish = ref(true);
const permEditGlobalKb = ref(false);
const permManageRouter = ref(false);

// Skill tab state
const skillId = ref("shot_planner");
const skillUiRenderer = ref("timeline");
const skillDefaultModelProfile = ref<string | null>(null);
const skillTools = ref<string[]>(["search", "embedding"]);
const skillKnowledgeScopes = ref<string[]>(["director_basic"]);
const skillInputSchemaText = ref('{"type":"object","properties":{"chapter_id":{"type":"string"}}}');
const skillOutputSchemaText = ref('{"type":"object","properties":{"shot_plan":{"type":"array"}}}');
const skillInitTemplate = ref("director_bootstrap_v1");

// Route tab state
const routeId = ref("route_scene_board");
const routePath = ref("/studio/scene-board");
const routeComponent = ref("StudioSceneBoardPage");
const routeFeatureId = ref("shot_planner");
const routeUiMode = ref("timeline");
const routeAllowedRolesCsv = ref("director,script_supervisor");
const routeDependsOnCsv = ref("rag,embedding,minio");

// Preview tab state
const previewRoleId = ref<string | null>(null);
const previewSkillId = ref<string | null>(null);
const previewResult = ref("");

const message = ref("");
const errorMessage = ref("");

// ─── Computed ─────────────────────────────────────────────────────────────────
const modelProfileOptions = computed(() =>
  modelProfiles.value.map((item) => ({
    label: `${item.purpose} · ${item.name} (${item.id})`,
    value: item.id,
  }))
);

const skillCheckboxOptions = computed(() => {
  const fromRegistry = skillRegistryItems.value.map(s => ({ label: s.skill_id, value: s.skill_id }));
  const defaults = ["shot_planner","dialogue_director","review_gate","i18n_adapter","continuity_checker","tts_director","timeline_editor","style_referee","culture_enforcer","camera_planner"].map(s => ({ label: s, value: s }));
  const existing = new Set(fromRegistry.map(o => o.value));
  return [...fromRegistry, ...defaults.filter(o => !existing.has(o.value))];
});

// ─── Table Columns ────────────────────────────────────────────────────────────
const roleColumns: DataTableColumns<RoleProfileResponse> = [
  { title: "Role", key: "role_id" },
  { title: "Skills", key: "default_skills", render: (row) => row.default_skills.join(", ") },
  {
    title: "Action",
    key: "action",
    render: (row) =>
      h(NSpace, { size: 6 }, {
        default: () => [
          h(NButton, { size: "tiny", onClick: () => useRole(row) }, { default: () => "填充" }),
          h(NButton, { size: "tiny", type: "error", onClick: () => void onDeleteRole(row.role_id) }, { default: () => "删除" }),
        ],
      }),
  },
];

const skillColumns: DataTableColumns<SkillRegistryResponse> = [
  { title: "Skill", key: "skill_id" },
  { title: "Renderer", key: "ui_renderer" },
  { title: "Tools", key: "tools_required", render: (row) => row.tools_required.join(", ") },
  {
    title: "Action",
    key: "action",
    render: (row) =>
      h(NSpace, { size: 6 }, {
        default: () => [
          h(NButton, { size: "tiny", onClick: () => useSkill(row) }, { default: () => "填充" }),
          h(NButton, { size: "tiny", type: "error", onClick: () => void onDeleteSkill(row.skill_id) }, { default: () => "删除" }),
        ],
      }),
  },
];

const routeColumns: DataTableColumns<FeatureRouteMapResponse> = [
  { title: "Route", key: "route_id" },
  { title: "Path", key: "path" },
  { title: "Roles", key: "allowed_roles", render: (row) => row.allowed_roles.join(", ") },
  {
    title: "Action",
    key: "action",
    render: (row) =>
      h(NSpace, { size: 6 }, {
        default: () => [
          h(NButton, { size: "tiny", onClick: () => useRoute(row) }, { default: () => "填充" }),
          h(NButton, { size: "tiny", type: "error", onClick: () => void onDeleteRoute(row.route_id) }, { default: () => "删除" }),
        ],
      }),
  },
];

// ─── Helpers ──────────────────────────────────────────────────────────────────
function stringifyError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function parseCsv(value: string): string[] {
  return value.split(",").map(s => s.trim()).filter(s => s.length > 0);
}

function parseObject(text: string): Record<string, unknown> {
  const parsed = JSON.parse(text) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("json must be object");
  return parsed as Record<string, unknown>;
}

function clearNotice(): void {
  message.value = "";
  errorMessage.value = "";
}

// ─── Template apply ───────────────────────────────────────────────────────────
function onApplyTemplate(templateId: string | null): void {
  if (!templateId) return;
  const t = ROLE_TEMPLATES.find(r => r.id === templateId);
  if (!t) return;
  roleId.value = t.id;
  rolePromptStyle.value = t.promptStyle;
  roleDefaultSkills.value = [...t.skills];
  roleDefaultScopes.value = [...t.scopes];
  permImport.value = true;
  permPublish.value = true;
  permEditGlobalKb.value = false;
  permManageRouter.value = false;
}

// ─── Fill forms from table rows ───────────────────────────────────────────────
function useRole(row: RoleProfileResponse): void {
  roleId.value = row.role_id;
  rolePromptStyle.value = row.prompt_style;
  roleDefaultSkills.value = [...row.default_skills];
  roleDefaultScopes.value = [...row.default_knowledge_scopes];
  roleDefaultModelProfile.value = row.default_model_profile || null;
  permImport.value = row.permissions.can_import_data;
  permPublish.value = row.permissions.can_publish_task;
  permEditGlobalKb.value = row.permissions.can_edit_global_knowledge;
  permManageRouter.value = row.permissions.can_manage_model_router;
  activeTab.value = "roles";
}

function useSkill(row: SkillRegistryResponse): void {
  skillId.value = row.skill_id;
  skillUiRenderer.value = row.ui_renderer;
  skillDefaultModelProfile.value = row.default_model_profile || null;
  skillTools.value = [...row.tools_required];
  skillKnowledgeScopes.value = [...row.required_knowledge_scopes];
  skillInputSchemaText.value = JSON.stringify(row.input_schema || {}, null, 2);
  skillOutputSchemaText.value = JSON.stringify(row.output_schema || {}, null, 2);
  skillInitTemplate.value = row.init_template || "";
  activeTab.value = "skills";
}

function useRoute(row: FeatureRouteMapResponse): void {
  routeId.value = row.route_id;
  routePath.value = row.path;
  routeComponent.value = row.component;
  routeFeatureId.value = row.feature_id;
  routeUiMode.value = row.ui_mode;
  routeAllowedRolesCsv.value = row.allowed_roles.join(",");
  routeDependsOnCsv.value = row.depends_on.join(",");
  activeTab.value = "routes";
}

// ─── API Calls ────────────────────────────────────────────────────────────────
async function onReloadAll(): Promise<void> {
  clearNotice();
  try {
    const [profiles, roles, skills, routes] = await Promise.all([
      listModelProfiles({ tenant_id: tenantId.value, project_id: projectId.value }),
      listRoleProfiles({ tenant_id: tenantId.value, project_id: projectId.value, keyword: keyword.value || undefined }),
      listSkillRegistry({ tenant_id: tenantId.value, project_id: projectId.value, keyword: keyword.value || undefined }),
      listFeatureRouteMaps({ tenant_id: tenantId.value, project_id: projectId.value, keyword: keyword.value || undefined }),
    ]);
    modelProfiles.value = profiles;
    roleProfiles.value = roles;
    skillRegistryItems.value = skills;
    featureRoutes.value = routes;
    message.value = "配置已刷新";
  } catch (error) {
    errorMessage.value = `reload failed: ${stringifyError(error)}`;
  }
}

async function onUpsertRole(): Promise<void> {
  clearNotice();
  try {
    await upsertRoleProfile(roleId.value, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      role_id: roleId.value,
      prompt_style: rolePromptStyle.value,
      default_skills: roleDefaultSkills.value,
      default_knowledge_scopes: roleDefaultScopes.value,
      default_model_profile: roleDefaultModelProfile.value || undefined,
      permissions: {
        can_import_data: permImport.value,
        can_publish_task: permPublish.value,
        can_edit_global_knowledge: permEditGlobalKb.value,
        can_manage_model_router: permManageRouter.value,
      },
      enabled: true,
      schema_version: "1.0",
    });
    await onReloadAll();
    message.value = `role upserted: ${roleId.value}`;
  } catch (error) {
    errorMessage.value = `upsert role failed: ${stringifyError(error)}`;
  }
}

async function onDeleteRole(targetRoleId: string): Promise<void> {
  clearNotice();
  try {
    await deleteRoleProfile(targetRoleId, { tenant_id: tenantId.value, project_id: projectId.value });
    await onReloadAll();
    message.value = `role deleted: ${targetRoleId}`;
  } catch (error) {
    errorMessage.value = `delete role failed: ${stringifyError(error)}`;
  }
}

async function onUpsertSkill(): Promise<void> {
  clearNotice();
  try {
    await upsertSkillRegistry(skillId.value, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      skill_id: skillId.value,
      input_schema: parseObject(skillInputSchemaText.value),
      output_schema: parseObject(skillOutputSchemaText.value),
      required_knowledge_scopes: skillKnowledgeScopes.value,
      default_model_profile: skillDefaultModelProfile.value || undefined,
      tools_required: skillTools.value,
      ui_renderer: skillUiRenderer.value,
      init_template: skillInitTemplate.value || undefined,
      enabled: true,
      schema_version: "1.0",
    });
    await onReloadAll();
    message.value = `skill upserted: ${skillId.value}`;
  } catch (error) {
    errorMessage.value = `upsert skill failed: ${stringifyError(error)}`;
  }
}

async function onDeleteSkill(targetSkillId: string): Promise<void> {
  clearNotice();
  try {
    await deleteSkillRegistry(targetSkillId, { tenant_id: tenantId.value, project_id: projectId.value });
    await onReloadAll();
    message.value = `skill deleted: ${targetSkillId}`;
  } catch (error) {
    errorMessage.value = `delete skill failed: ${stringifyError(error)}`;
  }
}

async function onUpsertRoute(): Promise<void> {
  clearNotice();
  try {
    await upsertFeatureRouteMap(routeId.value, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      route_id: routeId.value,
      path: routePath.value,
      component: routeComponent.value,
      feature_id: routeFeatureId.value,
      allowed_roles: parseCsv(routeAllowedRolesCsv.value),
      ui_mode: routeUiMode.value,
      depends_on: parseCsv(routeDependsOnCsv.value),
      enabled: true,
      schema_version: "1.0",
    });
    await onReloadAll();
    message.value = `route upserted: ${routeId.value}`;
  } catch (error) {
    errorMessage.value = `upsert route failed: ${stringifyError(error)}`;
  }
}

async function onDeleteRoute(targetRouteId: string): Promise<void> {
  clearNotice();
  try {
    await deleteFeatureRouteMap(targetRouteId, { tenant_id: tenantId.value, project_id: projectId.value });
    await onReloadAll();
    message.value = `route deleted: ${targetRouteId}`;
  } catch (error) {
    errorMessage.value = `delete route failed: ${stringifyError(error)}`;
  }
}

function onResolvePreview(): void {
  if (!previewRoleId.value || !previewSkillId.value) return;
  const role = roleProfiles.value.find(r => r.role_id === previewRoleId.value);
  const skill = skillRegistryItems.value.find(s => s.skill_id === previewSkillId.value);
  previewResult.value = JSON.stringify({
    role: { id: previewRoleId.value, prompt_style: role?.prompt_style, permissions: role?.permissions },
    skill: { id: previewSkillId.value, ui_renderer: skill?.ui_renderer, tools: skill?.tools_required },
    resolved_model: role?.default_model_profile || skill?.default_model_profile || "(inherit from routing)",
    kb_scopes: [...new Set([...(role?.default_knowledge_scopes || []), ...(skill?.required_knowledge_scopes || [])])],
  }, null, 2);
}

// ═══════════════════════════════════════════════════════════════════════════════
// 职业 KB 绑定
// ═══════════════════════════════════════════════════════════════════════════════

const kbBindRoleId = ref("");
const roleKBBindings = ref<KBMapEntry[]>([]);
const showKBPickerModal = ref(false);
const kbPickerKeyword = ref("");
const allKBPacks = ref<KBPackResponse[]>([]);

const filteredKBPacks = computed(() => {
  const kw = kbPickerKeyword.value.toLowerCase();
  return allKBPacks.value.filter(p => !kw || p.name.toLowerCase().includes(kw));
});

const roleKBColumns = computed<import("naive-ui").DataTableColumns<KBMapEntry>>(() => [
  { title: "KB名称", key: "kb_pack_name", ellipsis: { tooltip: true } },
  { title: "优先级", key: "priority", width: 80 },
  {
    title: "启用", key: "enabled", width: 70,
    render: (row: KBMapEntry) => h(NSwitch, {
      value: row.enabled, size: "small",
      "onUpdate:value": async (val: boolean) => {
        try {
          await updateRoleKBBinding(row.id, { enabled: val });
          await onLoadRoleKBBindings();
        } catch (e) { errorMessage.value = stringifyError(e); }
      },
    }),
  },
  {
    title: "操作", key: "action", width: 120,
    render: (row: KBMapEntry) => h(NSpace, { size: 6 }, {
      default: () => [
        h(NButton, {
          size: "tiny", onClick: async () => {
            try {
              await updateRoleKBBinding(row.id, { priority: (row.priority || 100) + 10 });
              await onLoadRoleKBBindings();
            } catch (e) { errorMessage.value = stringifyError(e); }
          },
        }, { default: () => "↑" }),
        h(NButton, {
          size: "tiny", onClick: async () => {
            try {
              await updateRoleKBBinding(row.id, { priority: Math.max(0, (row.priority || 100) - 10) });
              await onLoadRoleKBBindings();
            } catch (e) { errorMessage.value = stringifyError(e); }
          },
        }, { default: () => "↓" }),
        h(NButton, {
          size: "tiny", type: "error",
          onClick: async () => {
            try {
              await deleteRoleKBBinding(row.id);
              await onLoadRoleKBBindings();
              message.value = `已解绑 ${row.kb_pack_name}`;
            } catch (e) { errorMessage.value = stringifyError(e); }
          },
        }, { default: () => "解绑" }),
      ],
    }),
  },
]);

const kbPickerColumns = computed<import("naive-ui").DataTableColumns<KBPackResponse>>(() => [
  { title: "名称", key: "name", ellipsis: { tooltip: true } },
  { title: "语言", key: "language_code", width: 60 },
  { title: "状态", key: "status", width: 90 },
  {
    title: "操作", key: "action", width: 80,
    render: (row: KBPackResponse) => h(NButton, {
      size: "tiny", type: "primary",
      onClick: async () => {
        if (!kbBindRoleId.value) return;
        try {
          await createRoleKBBinding(kbBindRoleId.value, {
            tenant_id: tenantId.value, project_id: projectId.value,
            kb_pack_id: row.id, priority: 100, enabled: true,
          });
          showKBPickerModal.value = false;
          await onLoadRoleKBBindings();
          message.value = `已绑定 "${row.name}" → ${kbBindRoleId.value}`;
        } catch (e) { errorMessage.value = stringifyError(e); }
      },
    }, { default: () => "绑定" }),
  },
]);

async function onLoadRoleKBBindings(): Promise<void> {
  if (!kbBindRoleId.value) { roleKBBindings.value = []; return; }
  try {
    roleKBBindings.value = await listRoleKBBindings({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      role_id: kbBindRoleId.value,
    });
  } catch (e) { errorMessage.value = stringifyError(e); }
}

async function onLoadAllKBPacks(): Promise<void> {
  try {
    allKBPacks.value = await listKBPacks({ tenant_id: tenantId.value, project_id: projectId.value });
  } catch { /* silent */ }
}

// 在 showKBPickerModal 打开时加载资产池
watch(showKBPickerModal, (val) => { if (val) void onLoadAllKBPacks(); });

onMounted(() => {
  void onReloadAll();
});
</script>

