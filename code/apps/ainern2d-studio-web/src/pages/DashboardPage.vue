<template>
  <section class="grid cols-2">
    <article class="card">
      <h2>Open Run Preview</h2>
      <p class="muted">Enter project and run IDs, then jump to the preview workflow.</p>
      <div class="grid">
        <div>
          <label>Project ID</label>
          <input v-model="projectId" placeholder="project_xxx" />
        </div>
        <div>
          <label>Run ID</label>
          <input v-model="runId" placeholder="run_xxx" />
        </div>
        <div class="button-row">
          <button @click="openPreview">Open Preview</button>
        </div>
      </div>
    </article>
    <article class="card">
      <h2>MVP Scope</h2>
      <ul class="muted">
        <li>Entity continuity profile and approved variant lock.</li>
        <li>Multi-angle preview generation queue.</li>
        <li>Approve/reject/regenerate loop for preview variants.</li>
        <li>Per-entity stable voice binding.</li>
      </ul>
    </article>
  </section>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";

const router = useRouter();
const projectId = ref("");
const runId = ref("");

function openPreview(): void {
  if (!projectId.value || !runId.value) {
    return;
  }
  void router.push({
    name: "run-preview",
    params: {
      projectId: projectId.value,
      runId: runId.value,
    },
  });
}
</script>
