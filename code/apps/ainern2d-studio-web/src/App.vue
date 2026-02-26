<template>
  <div class="app-shell">
    <header class="app-header">
      <h1>Ainer Studio Preview Console</h1>
      <nav>
        <RouterLink to="/">Dashboard</RouterLink>
      </nav>
    </header>
    <main class="app-main">
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts"></script>
