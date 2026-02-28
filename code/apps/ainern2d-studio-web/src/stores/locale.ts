/**
 * Global Locale Store
 * Syncs with LoginPage via localStorage key "ainer_studio_locale"
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export type SupportedLocale = 'zh-CN' | 'en-US' | 'ja-JP' | 'es-ES' | 'ar-SA'
export const LOCALE_KEY = 'ainer_studio_locale'
const DEFAULT_LOCALE: SupportedLocale = 'zh-CN'

export const useLocaleStore = defineStore('locale', () => {
    const locale = ref<SupportedLocale>(
        (localStorage.getItem(LOCALE_KEY) as SupportedLocale) || DEFAULT_LOCALE
    )

    function setLocale(val: SupportedLocale) {
        locale.value = val
        localStorage.setItem(LOCALE_KEY, val)
        document.documentElement.lang = val
    }

    const isRTL = computed(() => locale.value === 'ar-SA')

    return { locale, setLocale, isRTL }
})
