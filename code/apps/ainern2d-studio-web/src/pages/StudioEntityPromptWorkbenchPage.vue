<template>
  <div class="entity-prompt-workbench">
    <NPageHeader @back="onBack" title="实体提示词工作台">
      <template #subtitle>
        <NText depth="3">{{ novelTitle || novelId }}</NText>
      </template>
      <template #extra>
        <NSpace>
          <NButton :loading="loading" @click="reload">刷新</NButton>
          <NButton type="primary" :loading="batchSaving" :disabled="dirtyCount === 0" @click="onBatchSave">
            批量保存 ({{ dirtyCount }})
          </NButton>
        </NSpace>
      </template>
    </NPageHeader>

    <NTabs v-model:value="activeTab" type="line" style="margin-top: 12px;">
      <NTabPane name="person" tab="角色 (person)">
        <EntityTypePanel :items="byType['person'] || []" :dirty-set="dirtySet" @update="onPromptUpdate" />
      </NTabPane>
      <NTabPane name="place" tab="场景 (place)">
        <EntityTypePanel :items="byType['place'] || []" :dirty-set="dirtySet" @update="onPromptUpdate" />
      </NTabPane>
      <NTabPane name="item" tab="道具 (item)">
        <EntityTypePanel :items="byType['item'] || []" :dirty-set="dirtySet" @update="onPromptUpdate" />
      </NTabPane>
      <NTabPane name="other" tab="其他">
        <EntityTypePanel :items="otherEntities" :dirty-set="dirtySet" @update="onPromptUpdate" />
      </NTabPane>
      <NTabPane name="beats" tab="章节节拍">
        <div v-if="chapterBeats.length === 0" style="padding: 20px;">
          <NEmpty description="暂无节拍数据，请先执行世界模型解析" />
        </div>
        <NCollapse v-else>
          <NCollapseItem
            v-for="ch in chapterBeats"
            :key="ch.chapter_id"
            :title="`第 ${ch.chapter_no} 章${ch.chapter_title ? ' — ' + ch.chapter_title : ''}`"
            :name="ch.chapter_id"
          >
            <div v-if="ch.beats.length">
              <NText strong>Beats</NText>
              <div v-for="(beat, i) in ch.beats" :key="i" class="beat-item">
                <NText code>{{ JSON.stringify(beat) }}</NText>
              </div>
            </div>
            <div v-if="ch.style_hints.length" style="margin-top: 8px;">
              <NText strong>Style Hints</NText>
              <div v-for="(hint, i) in ch.style_hints" :key="i" class="beat-item">
                <NText code>{{ JSON.stringify(hint) }}</NText>
              </div>
            </div>
            <NEmpty v-if="!ch.beats.length && !ch.style_hints.length" description="无节拍" />
          </NCollapseItem>
        </NCollapse>
      </NTabPane>
    </NTabs>
  </div>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, onMounted, ref, reactive } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  NButton,
  NCard,
  NCollapse,
  NCollapseItem,
  NEmpty,
  NInput,
  NPageHeader,
  NSpace,
  NTabPane,
  NTabs,
  NTag,
  NText,
  useMessage,
} from "naive-ui";
import {
  getEntityPrompts,
  updateAnchorPrompt,
  getChapterBeats,
  batchUpdateAnchorPrompts,
  type EntityPromptItem,
  type ChapterBeatItem,
} from "@/api/product";

const props = defineProps<{ novelId: string }>();

const route = useRoute();
const router = useRouter();
const message = useMessage();

const loading = ref(false);
const batchSaving = ref(false);
const activeTab = ref("person");
const novelTitle = ref("");

const byType = ref<Record<string, EntityPromptItem[]>>({});
const totalEntities = ref(0);
const chapterBeats = ref<ChapterBeatItem[]>([]);

// Track edits: entity_id -> new anchor_prompt
const editBuffer = reactive<Record<string, string>>({});
const dirtySet = reactive(new Set<string>());
const dirtyCount = computed(() => dirtySet.size);

const otherEntities = computed(() => {
  const mainTypes = new Set(["person", "place", "item"]);
  const result: EntityPromptItem[] = [];
  for (const [type, items] of Object.entries(byType.value)) {
    if (!mainTypes.has(type)) {
      result.push(...items);
    }
  }
  return result;
});

const tenantId = "default";
const projectId = "default";

function onBack() {
  router.push({ name: "studio-novel-detail", params: { novelId: props.novelId } });
}

function onPromptUpdate(entityId: string, newPrompt: string) {
  editBuffer[entityId] = newPrompt;
  dirtySet.add(entityId);
}

async function reload() {
  loading.value = true;
  try {
    const [promptsRes, beatsRes] = await Promise.all([
      getEntityPrompts(props.novelId, { tenant_id: tenantId, project_id: projectId }),
      getChapterBeats(props.novelId, { tenant_id: tenantId, project_id: projectId }),
    ]);
    byType.value = promptsRes.by_type;
    totalEntities.value = promptsRes.total;
    chapterBeats.value = beatsRes.chapters;
  } catch (e: any) {
    message.error(e?.response?.data?.detail || "加载失败");
  } finally {
    loading.value = false;
  }
}

async function onBatchSave() {
  const items = Array.from(dirtySet).map((eid) => ({
    entity_id: eid,
    anchor_prompt: editBuffer[eid] ?? "",
  }));
  if (!items.length) return;
  batchSaving.value = true;
  try {
    const res = await batchUpdateAnchorPrompts(props.novelId, { items });
    message.success(`已更新 ${res.updated} 个实体提示词`);
    dirtySet.clear();
    await reload();
  } catch (e: any) {
    message.error(e?.response?.data?.detail || "保存失败");
  } finally {
    batchSaving.value = false;
  }
}

onMounted(() => {
  reload();
});

// ---------------------------------------------------------------------------
// EntityTypePanel inline component
// ---------------------------------------------------------------------------
const EntityTypePanel = defineComponent({
  name: "EntityTypePanel",
  props: {
    items: { type: Array as () => EntityPromptItem[], required: true },
    dirtySet: { type: Set as unknown as () => Set<string>, required: true },
  },
  emits: ["update"],
  setup(props, { emit }) {
    return () => {
      if (!props.items.length) {
        return h(NEmpty, { description: "该类型暂无实体" });
      }
      return h("div", { class: "entity-panel-list" }, props.items.map((item) =>
        h(NCard, {
          key: item.entity_id,
          size: "small",
          class: props.dirtySet.has(item.entity_id) ? "entity-card entity-card--dirty" : "entity-card",
          style: "margin-bottom: 8px;",
        }, {
          header: () => h(NSpace, { align: "center" }, () => [
            h(NText, { strong: true }, () => item.label),
            item.canonical_label ? h(NTag, { size: "small", bordered: false }, () => item.canonical_label) : null,
            ...item.alias_list.map((a) => h(NTag, { size: "tiny", type: "info", bordered: false, key: a }, () => a)),
          ]),
          default: () => h(NInput, {
            type: "textarea",
            rows: 3,
            value: item.anchor_prompt ?? "",
            placeholder: "输入 anchor prompt（用于生图/角色一致性）",
            onUpdateValue: (val: string) => emit("update", item.entity_id, val),
          }),
        }),
      ));
    };
  },
});
</script>

<style scoped>
.entity-prompt-workbench {
  padding: 16px;
  max-width: 1200px;
  margin: 0 auto;
}
.entity-panel-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.entity-card--dirty {
  border-left: 3px solid #18a058;
}
.beat-item {
  padding: 4px 0;
  border-bottom: 1px dashed #e0e0e0;
}
</style>
