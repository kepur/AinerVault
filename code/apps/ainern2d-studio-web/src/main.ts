import { createApp } from "vue";
import { createPinia } from "pinia";

import App from "./App.vue";
import router from "./router";
import "./styles.css";

const pinia = createPinia();
const app = createApp(App).use(pinia).use(router);

// Initialize locale store early so all pages read the correct language immediately
import { useLocaleStore } from "@/stores/locale";
const localeStore = useLocaleStore(pinia);
// Apply initial locale to document
document.documentElement.lang = localeStore.locale;

// Sync locale if LoginPage changes it while app is alive
window.addEventListener("storage", (e) => {
    if (e.key === "ainer_studio_locale" && e.newValue) {
        localeStore.setLocale(e.newValue as "zh-CN" | "en-US" | "ja-JP" | "es-ES" | "ar-SA");
    }
});

app.mount("#app");
