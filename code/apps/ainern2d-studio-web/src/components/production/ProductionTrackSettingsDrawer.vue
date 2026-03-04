<template>
  <NDrawer :show="show" width="420" placement="right" @update:show="(v) => emit('update:show', v)">
    <NDrawerContent title="Track Settings" closable>
      <NFormItem label="Track">
        <NInput :value="trackType" disabled />
      </NFormItem>
      <NFormItem label="Max Inflight">
        <NInputNumber :value="maxInflight" :min="1" :max="50" @update:value="(v) => emit('update:maxInflight', Number(v || 1))" />
      </NFormItem>
      <NFormItem label="Auto Retry">
        <NSwitch :value="autoRetry" @update:value="(v) => emit('update:autoRetry', v)" />
      </NFormItem>
    </NDrawerContent>
  </NDrawer>
</template>

<script setup lang="ts">
import { NDrawer, NDrawerContent, NFormItem, NInput, NInputNumber, NSwitch } from "naive-ui";

defineProps<{
  show: boolean;
  trackType: string;
  maxInflight: number;
  autoRetry: boolean;
}>();

const emit = defineEmits<{
  (event: "update:show", value: boolean): void;
  (event: "update:maxInflight", value: number): void;
  (event: "update:autoRetry", value: boolean): void;
}>();
</script>
