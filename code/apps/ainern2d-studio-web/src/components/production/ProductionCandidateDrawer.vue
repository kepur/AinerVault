<template>
  <NDrawer :show="show" width="520" placement="right" @update:show="(v) => emit('update:show', v)">
    <NDrawerContent title="Candidates" closable>
      <NEmpty v-if="!items.length" description="No candidates yet" />
      <NList v-else>
        <NListItem v-for="item in items" :key="item.id">
          <NSpace justify="space-between" style="width: 100%">
            <NSpace vertical :size="2">
              <NText>{{ item.label }}</NText>
              <NText depth="3" style="font-size: 12px">{{ item.subtitle || "" }}</NText>
            </NSpace>
            <NSpace>
              <NTag v-if="item.selected" type="success" :bordered="false">Selected</NTag>
              <NButton size="tiny" :disabled="item.selected" @click="emit('select', item.id)">
                {{ item.selected ? "Using" : "Use" }}
              </NButton>
            </NSpace>
          </NSpace>
        </NListItem>
      </NList>
    </NDrawerContent>
  </NDrawer>
</template>

<script setup lang="ts">
import { NButton, NDrawer, NDrawerContent, NEmpty, NList, NListItem, NSpace, NTag, NText } from "naive-ui";

defineProps<{
  show: boolean;
  items: Array<{ id: string; label: string; subtitle?: string; selected?: boolean }>;
}>();

const emit = defineEmits<{
  (event: "update:show", value: boolean): void;
  (event: "select", candidateId: string): void;
}>();
</script>
