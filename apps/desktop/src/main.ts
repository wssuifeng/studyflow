import { createApp } from 'vue'
import App from './app/App.vue'
import './shared/styles/index.css'
import './shared/ui/readingPreferences'
import { initializeThemes } from './shared/themes'

initializeThemes()
createApp(App).mount('#app')
