<template>
  <NCard title="Track Summary">
    <NDataTable :columns="columns" :data="items" :pagination="{ pageSize: 6 }" />
  </NCard>
</template>

<script setup lang="ts">
import { computed, h } from "vue";
import { NDataTable, NTag, type DataTableColumns } from "naive-ui";

const props = defineProps<{
  items: Array<{
    track_run_id: string;
    track_type: string;
    worker_type?: string | null;
    status: string;
    blocked_reason?: string | null;
    total_units: number;
    success_units: number;
    failed_units: number;
    running_units: number;
  }>;
}>();

function statusTag(status: string): "default" | "success" | "warning" | "error" | "info" {
  if (status === "done" || status === "success") return "success";
  if (status === "failed") return "error";
  if (status === "blocked" || status === "partial") return "info";
  if (status === "running" || status === "queued") return "warning";
  return "default";
}

const columns = computed<DataTableColumns<(typeof props.items)[number]>>(() => [
  { title: "Track", key: "track_type" },
  { title: "Worker", key: "worker_type" },
  {
    title: "Status",
    key: "status",
    render: (row) => h(NTag, { type: statusTag(row.status), bordered: false }, { default: () => row.status }),
  },
  {
    title: "Units",
    key: "units",
    render: (row) => `${row.success_units}/${row.total_units} (failed:${row.failed_units}, running:${row.running_units})`,
  },
  { title: "Blocked", key: "blocked_reason" },
]);
</script>
