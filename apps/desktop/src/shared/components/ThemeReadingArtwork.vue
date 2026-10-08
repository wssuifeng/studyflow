<script setup lang="ts">
import { computed, ref } from 'vue'
import { imageIntensity, themeAssets } from '../themes/display-loader'
// Presentation only: no API, course state, write operation or saved-state claim.
const artwork = computed(() => themeAssets('illustration')[0] ?? null)
const failedUrl = ref('')
</script>
<template>
  <figure v-if="artwork && artwork.url !== failedUrl" class="theme-reading-artwork" :class="{'is-subtle': imageIntensity === 'subtle'}" aria-hidden="true" :style="{'aspect-ratio': artwork.aspectRatio.replace(':',' / ')}">
    <img :src="artwork.url" alt="" draggable="false" decoding="async" @error="failedUrl=artwork?.url || ''" />
  </figure>
</template>
