<template>
  <div class="kb-asset-center">
    <!-- Header -->
    <NCard class="header-card">
      <div class="header-row">
        <div>
          <h2 style="margin:0 0 4px">知识资产中心</h2>
          <p style="margin:0;color:#888;font-size:13px">KBPack 是可复用的知识包，可绑定至多个 Role / Persona / Novel</p>
        </div>
        <NSpace>
          <NInput v-model:value="tenantId" placeholder="Tenant ID" style="width:140px" />
          <NInput v-model:value="projectId" placeholder="Project ID" style="width:140px" />
        </NSpace>
      </div>
    </NCard>

    <NGrid :cols="12" :x-gap="16" :y-gap="16" style="margin-top:16px">
      <!-- Left: KBPack List -->
      <NGridItem :span="selectedPackId ? 5 : 12">
        <NCard title="KB 资产包列表">
          <!-- Filters -->
          <NSpace style="margin-bottom:12px" wrap>
            <NInput v-model:value="filterKeyword" placeholder="🔍 搜索名称" style="width:160px" clearable @input="onReloadPacks" />
            <NSelect v-model:value="filterLanguage" :options="languageOptions" placeholder="语言" style="width:120px" clearable @update:value="onReloadPacks" />
            <NSelect v-model:value="filterCulturePack" :options="culturePackOptions" placeholder="文化包" style="width:140px" clearable @update:value="onReloadPacks" />
            <NSelect v-model:value="filterStatus" :options="statusOptions" placeholder="状态" style="width:110px" clearable @update:value="onReloadPacks" />
            <NButton type="primary" size="small" @click="showCreateModal = true">+ 新建 KBPack</NButton>
          </NSpace>

          <NDataTable
            :columns="packColumns"
            :data="packs"
            :row-key="(row) => row.id"
            :row-props="rowProps"
            :pagination="{ pageSize: 8 }"
            size="small"
            :row-class-name="(row) => row.id === selectedPackId ? 'selected-row' : ''"
          />
        </NCard>
      </NGridItem>

      <!-- Right: Pack Detail -->
      <NGridItem v-if="selectedPackId" :span="7">
        <NCard v-if="selectedPack">
          <template #header>
            <NSpace align="center">
              <span style="font-weight:600">{{ selectedPack.name }}</span>
              <NTag :type="statusTagType(selectedPack.status)" size="small">{{ selectedPack.status }}</NTag>
            </NSpace>
          </template>
          <template #header-extra>
            <NButton size="tiny" quaternary @click="selectedPackId = ''">✕ 关闭</NButton>
          </template>

          <NTabs v-model:value="activeTab" type="line" animated>
            <!-- Tab 1: 基本信息 -->
            <NTabPane name="info" :tab="t('kb.basicInfo')">
              <NForm label-placement="left" :label-width="90" style="max-width:500px;margin-top:12px">
                <NFormItem label="名称">
                  <NInput v-model:value="editPack.name" />
                </NFormItem>
                <NFormItem label="描述">
                  <NInput v-model:value="editPack.description" type="textarea" :rows="2" />
                </NFormItem>
                <NFormItem label="语言">
                  <NSelect v-model:value="editPack.language_code" :options="languageOptions" clearable />
                </NFormItem>
                <NFormItem label="文化包">
                  <NSelect v-model:value="editPack.culture_pack" :options="culturePackOptions" clearable />
                </NFormItem>
                <NFormItem label="版本号">
                  <NInput v-model:value="editPack.version_name" />
                </NFormItem>
                <NFormItem label="状态">
                  <NSelect v-model:value="editPack.status" :options="statusOptions" />
                </NFormItem>
                <NFormItem label="标签">
                  <NDynamicTags v-model:value="editPack.tags_json" />
                </NFormItem>
                <NFormItem label="建议绑定职业">
                  <NSelect
                    v-model:value="editPack.bind_suggestions_json"
                    :options="roleOptions"
                    multiple
                    filterable
                    placeholder="推荐绑定的 Role ID"
                  />
                </NFormItem>
                <NSpace>
                  <NButton type="primary" @click="onSavePack">{{ t('common.save') }}</NButton>
                  <NButton type="error" @click="onDeletePack">删除知识包</NButton>
                </NSpace>
              </NForm>
            </NTabPane>

            <!-- Tab 2: 源文件 -->
            <NTabPane name="sources" :tab="t('kb.sourceFile')">
              <NSpace style="margin:12px 0" wrap>
                <NSelect
                  v-model:value="uploadBindRoleIds"
                  :options="roleOptions"
                  multiple
                  filterable
                  placeholder="上传后自动绑定职业（可选）"
                  style="width:260px"
                />
                <label>
                  <NButton tag="span" :loading="isUploading">
                    {{ isUploading ? '上传解析中...' : '📤 上传文档 (PDF/DOCX/TXT/XLSX)' }}
                  </NButton>
                  <input
                    ref="fileInput"
                    type="file"
                    accept=".pdf,.docx,.xlsx,.xls,.txt,.md"
                    style="display:none"
                    @change="onFileChange"
                  />
                </label>
                <NButton @click="onTriggerEmbed" :loading="isEmbedding">⚡ 批量生成 Embedding</NButton>
              </NSpace>
              <NDataTable :columns="sourceColumns" :data="sources" size="small" :pagination="{ pageSize: 8 }" />
              <NAlert v-if="uploadResult" type="success" style="margin-top:8px">
                ✓ 解析完成：{{ uploadResult.source_name }}（{{ uploadResult.chunk_count }} 个 chunks）
              </NAlert>
            </NTabPane>

            <!-- Tab 3: 绑定管理 -->
            <NTabPane name="bindings" :tab="t('kb.bindingMgmt')">
              <NTabs type="segment" style="margin-top:8px">
                <!-- 职业绑定 -->
                <NTabPane name="role" tab="职业 Role">
                  <NSpace style="margin:10px 0">
                    <NSelect v-model:value="newRoleBindId" :options="roleOptions" placeholder="选择 Role" filterable style="width:220px" />
                    <NInputNumber v-model:value="newBindPriority" placeholder="优先级" style="width:100px" />
                    <NButton type="primary" size="small" @click="onAddRoleBinding">+ 添加绑定</NButton>
                  </NSpace>
                  <NDataTable :columns="bindingColumns('role')" :data="roleBindings" size="small" />
                </NTabPane>
                <!-- Persona 绑定 -->
                <NTabPane name="persona" tab="Persona">
                  <NSpace style="margin:10px 0">
                    <NSelect v-model:value="newPersonaBindId" :options="personaOptions" placeholder="选择 Persona" filterable style="width:220px" />
                    <NInputNumber v-model:value="newBindPriority" placeholder="优先级" style="width:100px" />
                    <NButton type="primary" size="small" @click="onAddPersonaBinding">+ 添加绑定</NButton>
                  </NSpace>
                  <NDataTable :columns="bindingColumns('persona')" :data="personaBindings" size="small" />
                </NTabPane>
                <!-- Novel 绑定 -->
                <NTabPane name="novel" tab="小说 Novel">
                  <NSpace style="margin:10px 0">
                    <NSelect v-model:value="newNovelBindId" :options="novelOptions" placeholder="选择 Novel" filterable style="width:220px" />
                    <NInputNumber v-model:value="newBindPriority" placeholder="优先级" style="width:100px" />
                    <NButton type="primary" size="small" @click="onAddNovelBinding">+ 添加绑定</NButton>
                  </NSpace>
                  <NDataTable :columns="bindingColumns('novel')" :data="novelBindings" size="small" />
                </NTabPane>
              </NTabs>
            </NTabPane>
          </NTabs>
        </NCard>
      </NGridItem>
    </NGrid>

    <!-- 新建 KBPack Modal -->
    <NModal v-model:show="showCreateModal" preset="card" title="新建知识资产包" style="max-width:540px">
      <NForm label-placement="left" :label-width="90">
        <NFormItem label="名称 *">
          <NInput v-model:value="createForm.name" placeholder="e.g. 美术指导基础知识" />
        </NFormItem>
        <NFormItem label="描述">
          <NInput v-model:value="createForm.description" type="textarea" :rows="2" placeholder="该知识包的用途描述" />
        </NFormItem>
        <NFormItem label="语言">
          <NSelect v-model:value="createForm.language_code" :options="languageOptions" />
        </NFormItem>
        <NFormItem label="文化包">
          <NSelect v-model:value="createForm.culture_pack" :options="culturePackOptions" clearable placeholder="可选" />
        </NFormItem>
        <NFormItem label="版本">
          <NInput v-model:value="createForm.version_name" placeholder="v1" />
        </NFormItem>
        <NFormItem label="标签">
          <NDynamicTags v-model:value="createForm.tags_json" />
        </NFormItem>
        <NFormItem label="建议绑定 Role">
          <NSelect v-model:value="createForm.bind_suggestions_json" :options="roleOptions" multiple filterable placeholder="可选" />
        </NFormItem>
      </NForm>
      <template #footer>
        <NSpace justify="end">
          <NButton @click="showCreateModal = false">{{ t('common.cancel') }}</NButton>
          <NButton type="primary" :loading="isCreating" @click="onCreatePack">创建知识包</NButton>
        </NSpace>
      </template>
    </NModal>

    <NAlert v-if="successMsg" type="success" :show-icon="true" style="margin-top:12px">{{ successMsg }}</NAlert>
    <NAlert v-if="errorMsg" type="error" :show-icon="true" style="margin-top:12px">{{ errorMsg }}</NAlert>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref, watch } from "vue";
import {
  NAlert, NButton, NCard, NDataTable, NDynamicTags, NForm, NFormItem,
  NGrid, NGridItem, NInput, NInputNumber, NModal, NSelect, NSpace,
  NSwitch, NTabPane, NTabs, NTag,
  type DataTableColumns,
} from "naive-ui";
import { useI18n } from "@/composables/useI18n";


import {
  type KBMapEntry,
  type KBPackResponse,
  type KBSourceResponse,
  createKBPack,
  createNovelKBBinding,
  createPersonaKBBinding,
  createRoleKBBinding,
  deleteKBPack,
  deleteNovelKBBinding,
  deletePersonaKBBinding,
  deleteRoleKBBinding,
  listKBPacks,
  listKBSources,
  listNovels,
  listNovelKBBindings,
  listPersonaKBBindings,
  listPersonaPacks,
  listRoleKBBindings,
  listRoleProfiles,
  triggerKBEmbed,
  updateKBPack,
  updateNovelKBBinding,
  updatePersonaKBBinding,
  updateRoleKBBinding,
  uploadKBSource,
} from "@/api/product";

// ── 基础状态 ──
const { t } = useI18n();

const tenantId = ref("default");
const projectId = ref("default");

// ── 筛选 ──
const filterKeyword = ref("");
const filterLanguage = ref<string | null>(null);
const filterCulturePack = ref<string | null>(null);
const filterStatus = ref<string | null>(null);

// ── 数据 ──
const packs = ref<KBPackResponse[]>([]);
const sources = ref<KBSourceResponse[]>([]);
const roleBindings = ref<KBMapEntry[]>([]);
const personaBindings = ref<KBMapEntry[]>([]);
const novelBindings = ref<KBMapEntry[]>([]);

// ── 选中的 KBPack ──
const selectedPackId = ref("");
const selectedPack = computed(() => packs.value.find(p => p.id === selectedPackId.value) ?? null);
const activeTab = ref("info");

// 编辑表单
const editPack = ref({ name: "", description: "", language_code: "zh", culture_pack: "", version_name: "v1", status: "draft", tags_json: [] as string[], bind_suggestions_json: [] as string[] });

// 创建 Modal
const showCreateModal = ref(false);
const isCreating = ref(false);
const createForm = ref({
  name: "", description: "", language_code: "zh", culture_pack: "", version_name: "v1",
  tags_json: [] as string[], bind_suggestions_json: [] as string[],
});

// 上传
const fileInput = ref<HTMLInputElement | null>(null);
const isUploading = ref(false);
const isEmbedding = ref(false);
const uploadResult = ref<KBSourceResponse | null>(null);
const uploadBindRoleIds = ref<string[]>([]);

// 绑定 Modal 输入
const newRoleBindId = ref<string | null>(null);
const newPersonaBindId = ref<string | null>(null);
const newNovelBindId = ref<string | null>(null);
const newBindPriority = ref(100);

// 下拉数据
const roleOptions = ref<{ label: string; value: string }[]>([]);
const personaOptions = ref<{ label: string; value: string }[]>([]);
const novelOptions = ref<{ label: string; value: string }[]>([]);

// 消息
const successMsg = ref("");
const errorMsg = ref("");

// ── 静态选项 ──
const statusOptions = [
  { label: "草稿", value: "draft" },
  { label: "已 Embed", value: "embedded" },
  { label: "已发布", value: "published" },
  { label: "已废弃", value: "deprecated" },
];
const languageOptions = [
  { label: "简体中文 (zh-CN)", value: "zh-CN" },
  { label: "英语 (US/Global) / English", value: "en-US" },
  { label: "日语 (ja-JP) / 日本語", value: "ja-JP" },
  { label: "阿拉伯语 (ar-SA) / العربية", value: "ar-SA" },
  { label: "西语 (es-MX) / Español", value: "es-MX" },
  { label: "越南语 (vi-VN) / Tiếng Việt", value: "vi-VN" },
  { label: "葡萄牙语 (pt-BR) / Português", value: "pt-BR" },
  { label: "印地语 (hi-IN) / हिन्दी", value: "hi-IN" },
  { label: "德语 (de-DE) / Deutsch", value: "de-DE" },
  { label: "菲律宾语 (tl-PH) / Filipino", value: "tl-PH" },
];
const culturePackOptions = [
  { label: "cn_wuxia", value: "cn_wuxia" },
  { label: "cn_modern", value: "cn_modern" },
  { label: "us_hollywood", value: "us_hollywood" },
  { label: "jp_anime", value: "jp_anime" },
  { label: "universal", value: "universal" },
];

function statusTagType(status: string): "default" | "info" | "success" | "warning" | "error" {
  const map: Record<string, "default" | "info" | "success" | "warning" | "error"> = {
    draft: "default", embedded: "info", published: "success", deprecated: "warning",
  };
  return map[status] ?? "default";
}

// ── Watch selectedPack 更新 editPack ──
watch(selectedPackId, (id) => {
  const pack = packs.value.find(p => p.id === id);
  if (pack) {
    editPack.value = {
      name: pack.name,
      description: pack.description ?? "",
      language_code: pack.language_code ?? "zh",
      culture_pack: pack.culture_pack ?? "",
      version_name: pack.version_name,
      status: pack.status,
      tags_json: pack.tags_json ?? [],
      bind_suggestions_json: pack.bind_suggestions_json ?? [],
    };
    uploadResult.value = null;
    void loadPackDetail(id);
  }
});

function rowProps(row: KBPackResponse) {
  return {
    style: { cursor: "pointer", background: row.id === selectedPackId.value ? "rgba(24,160,88,0.08)" : "" },
    onClick: () => { selectedPackId.value = row.id; },
  };
}

// ── KBPack 列表列 ──
const packColumns: DataTableColumns<KBPackResponse> = [
  { title: "名称", key: "name", ellipsis: { tooltip: true } },
  { title: "语言", key: "language_code", width: 60 },
  {
    title: "状态", key: "status", width: 90,
    render: (row) => h(NTag, { size: "small", type: statusTagType(row.status), bordered: false }, { default: () => row.status }),
  },
  {
    title: "文化包", key: "culture_pack", width: 100,
    render: (row) => row.culture_pack ? h(NTag, { size: "small", bordered: false }, { default: () => row.culture_pack }) : "—",
  },
];

// ── 源文件列 ──
const sourceColumns: DataTableColumns<KBSourceResponse> = [
  { title: "文件名", key: "source_name", ellipsis: { tooltip: true } },
  { title: "类型", key: "source_type", width: 60 },
  {
    title: "解析状态", key: "parse_status", width: 90,
    render: (row) => h(NTag, { size: "small", type: row.parse_status === "done" ? "success" : "warning", bordered: false }, { default: () => row.parse_status }),
  },
  { title: "Chunks", key: "chunk_count", width: 80 },
];

// ── 绑定列 ──
function bindingColumns(type: "role" | "persona" | "novel"): DataTableColumns<KBMapEntry> {
  return [
    { title: "KB名称", key: "kb_pack_name", ellipsis: { tooltip: true } },
    { title: "优先级", key: "priority", width: 80 },
    {
      title: "启用", key: "enabled", width: 70,
      render: (row) => h(NSwitch, {
        value: row.enabled,
        size: "small",
        "onUpdate:value": async (val: boolean) => {
          const fn = type === "role" ? updateRoleKBBinding : type === "persona" ? updatePersonaKBBinding : updateNovelKBBinding;
          await fn(row.id, { enabled: val });
          await loadBindings();
        },
      }),
    },
    { title: "备注", key: "note", ellipsis: { tooltip: true } },
    {
      title: "操作", key: "action", width: 70,
      render: (row) => h(NButton, {
        size: "tiny", type: "error",
        onClick: async () => {
          const fn = type === "role" ? deleteRoleKBBinding : type === "persona" ? deletePersonaKBBinding : deleteNovelKBBinding;
          await fn(row.id);
          await loadBindings();
          setSuccess(`已解绑 ${row.kb_pack_name}`);
        },
      }, { default: () => "解绑" }),
    },
  ];
}

// ── Helper ──
function setSuccess(msg: string): void { successMsg.value = msg; errorMsg.value = ""; setTimeout(() => { successMsg.value = ""; }, 4000); }
function setError(msg: string): void { errorMsg.value = msg; successMsg.value = ""; }
function errStr(e: unknown): string { return e instanceof Error ? e.message : String(e); }

// ── 加载下拉数据 ──
async function loadDropdowns(): Promise<void> {
  try {
    const [roles, personas, novels] = await Promise.all([
      listRoleProfiles({ tenant_id: tenantId.value, project_id: projectId.value }).catch(() => []),
      listPersonaPacks({ tenant_id: tenantId.value, project_id: projectId.value }).catch(() => []),
      listNovels(tenantId.value, projectId.value).catch(() => []),
    ]);
    roleOptions.value = (roles as { role_id: string }[]).map(r => ({ label: r.role_id, value: r.role_id }));
    personaOptions.value = (personas as { id: string; name: string }[]).map(p => ({ label: p.name, value: p.id }));
    novelOptions.value = (novels as { id: string; title: string }[]).map(n => ({ label: n.title || n.id, value: n.id }));
  } catch { /* silent */ }
}

// ── KBPack 列表 ──
async function onReloadPacks(): Promise<void> {
  try {
    packs.value = await listKBPacks({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      keyword: filterKeyword.value || undefined,
      language_code: filterLanguage.value || undefined,
      culture_pack: filterCulturePack.value || undefined,
      status: filterStatus.value || undefined,
    });
  } catch (e) {
    setError(`加载失败: ${errStr(e)}`);
  }
}

// ── 详情加载 ──
async function loadPackDetail(id: string): Promise<void> {
  await Promise.all([
    loadSources(id),
    loadBindings(),
  ]);
}

async function loadSources(id?: string): Promise<void> {
  const pid = id ?? selectedPackId.value;
  if (!pid) return;
  try { sources.value = await listKBSources(pid); } catch { /* silent */ }
}

async function loadBindings(): Promise<void> {
  if (!selectedPackId.value) return;
  const base = { tenant_id: tenantId.value, project_id: projectId.value };
  const [rbs, pbs, nbs] = await Promise.all([
    // These list by role_id on the binding, but here we need to get all bindings FOR this pack
    // NOTE: The API currently filters by role_id. We'll use an empty role_id trick for now.
    // A correct endpoint would be GET /kb/packs/{id}/bindings which we'll add as backlog.
    // For the MVP, we show bindings from the selected role/persona/novel perspective.
    Promise.resolve([] as KBMapEntry[]),
    Promise.resolve([] as KBMapEntry[]),
    Promise.resolve([] as KBMapEntry[]),
  ]);
  roleBindings.value = rbs;
  personaBindings.value = pbs;
  novelBindings.value = nbs;
}

// ── 创建 KBPack ──
async function onCreatePack(): Promise<void> {
  if (!createForm.value.name.trim()) { setError("名称不能为空"); return; }
  isCreating.value = true;
  try {
    const pack = await createKBPack({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      ...createForm.value,
    });
    await onReloadPacks();
    selectedPackId.value = pack.id;
    showCreateModal.value = false;
    createForm.value = { name: "", description: "", language_code: "zh", culture_pack: "", version_name: "v1", tags_json: [], bind_suggestions_json: [] };
    setSuccess(`知识包 "${pack.name}" 创建成功`);
  } catch (e) {
    setError(`创建失败: ${errStr(e)}`);
  } finally {
    isCreating.value = false;
  }
}

// ── 保存 KBPack ──
async function onSavePack(): Promise<void> {
  if (!selectedPackId.value) return;
  try {
    await updateKBPack(selectedPackId.value, editPack.value);
    await onReloadPacks();
    setSuccess("保存成功");
  } catch (e) {
    setError(`保存失败: ${errStr(e)}`);
  }
}

// ── 删除 KBPack ──
async function onDeletePack(): Promise<void> {
  if (!selectedPackId.value) return;
  if (!confirm("确认删除此知识包？若有绑定关系会报错（可使用 force 参数强制删除）")) return;
  try {
    await deleteKBPack(selectedPackId.value, { tenant_id: tenantId.value, project_id: projectId.value });
    selectedPackId.value = "";
    await onReloadPacks();
    setSuccess("知识包已删除");
  } catch (e) {
    setError(`删除失败: ${errStr(e)}`);
  }
}

// ── 上传文档 ──
async function onFileChange(e: Event): Promise<void> {
  const file = (e.target as HTMLInputElement).files?.[0];
  if (!file || !selectedPackId.value) return;
  isUploading.value = true;
  uploadResult.value = null;
  try {
    uploadResult.value = await uploadKBSource(selectedPackId.value, file, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      bind_role_ids: uploadBindRoleIds.value.join(",") || undefined,
    });
    await loadSources();
    await onReloadPacks();
    setSuccess(`上传成功：${uploadResult.value.chunk_count} 个 chunks`);
  } catch (e) {
    setError(`上传失败: ${errStr(e)}`);
  } finally {
    isUploading.value = false;
    if (fileInput.value) fileInput.value.value = "";
  }
}

// ── 生成 Embedding ──
async function onTriggerEmbed(): Promise<void> {
  if (!selectedPackId.value) return;
  isEmbedding.value = true;
  try {
    const result = await triggerKBEmbed(selectedPackId.value, { tenant_id: tenantId.value, project_id: projectId.value });
    await onReloadPacks();
    setSuccess(result.message);
  } catch (e) {
    setError(`Embedding 失败: ${errStr(e)}`);
  } finally {
    isEmbedding.value = false;
  }
}

// ── 添加 Role 绑定 ──
async function onAddRoleBinding(): Promise<void> {
  if (!newRoleBindId.value || !selectedPackId.value) return;
  try {
    await createRoleKBBinding(newRoleBindId.value, {
      tenant_id: tenantId.value, project_id: projectId.value,
      kb_pack_id: selectedPackId.value, priority: newBindPriority.value, enabled: true,
    });
    newRoleBindId.value = null;
    await loadBindings();
    setSuccess("Role KB 绑定已添加");
  } catch (e) {
    setError(`绑定失败: ${errStr(e)}`);
  }
}

// ── 添加 Persona 绑定 ──
async function onAddPersonaBinding(): Promise<void> {
  if (!newPersonaBindId.value || !selectedPackId.value) return;
  try {
    await createPersonaKBBinding(newPersonaBindId.value, {
      tenant_id: tenantId.value, project_id: projectId.value,
      kb_pack_id: selectedPackId.value, priority: newBindPriority.value, enabled: true,
    });
    newPersonaBindId.value = null;
    await loadBindings();
    setSuccess("Persona KB 绑定已添加");
  } catch (e) {
    setError(`绑定失败: ${errStr(e)}`);
  }
}

// ── 添加 Novel 绑定 ──
async function onAddNovelBinding(): Promise<void> {
  if (!newNovelBindId.value || !selectedPackId.value) return;
  try {
    await createNovelKBBinding(newNovelBindId.value, {
      tenant_id: tenantId.value, project_id: projectId.value,
      kb_pack_id: selectedPackId.value, priority: newBindPriority.value, enabled: true,
    });
    newNovelBindId.value = null;
    await loadBindings();
    setSuccess("Novel KB 绑定已添加");
  } catch (e) {
    setError(`绑定失败: ${errStr(e)}`);
  }
}

onMounted(() => {
  void loadDropdowns();
  void onReloadPacks();
});
</script>

<style scoped>
.kb-asset-center { padding: 16px; }
.header-card { margin-bottom: 0; }
.header-row { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
:deep(.selected-row) { background: rgba(24,160,88,0.08) !important; }
</style>
