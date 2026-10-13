<script setup lang="ts">
const props=defineProps<{name:string}>()
const paths:Record<string,string[]>={
  note:['M5 3h8l3 3v11H5z','M13 3v4h3','M8 10h5M8 13h5'],
  more:['M4 10h.01M10 10h.01M16 10h.01'],
  close:['m5 5 10 10M15 5 5 15'],
  chevron:['m6 8 4 4 4-4'],
  return:['m7 5-4 4 4 4','M3 9h9a4 4 0 0 1 0 8h-2'],
  pin:['m7 3 6 0-1 5 3 3H5l3-3z','M10 11v6'],
  expand:['M7 3H4a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-3','M12 3h5v5M17 3l-8 8'],
  quote:['M4 7h5v5H4zM12 7h5v5h-5z','M9 12c0 2-1 3-3 4M17 12c0 2-1 3-3 4'],
  search:['M14 8a6 6 0 1 1-12 0 6 6 0 0 1 12 0','m13 13 5 5'],
  read:['M2 4h6l2 2 2-2h6v12h-6l-2 2-2-2H2z','M10 6v12'],
  undo:['M6 4 2 8l4 4','M2 8h9a5 5 0 0 1 0 10'],
  redo:['m14 4 4 4-4 4','M18 8H9a5 5 0 0 0 0 10'],
  check:['m4 10 4 4 8-9'],
  list:['M7 5h10M7 10h10M7 15h10','M3 5h.01M3 10h.01M3 15h.01'],
}
</script>
<template><svg class="ui-icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" :stroke-width="props.name==='more'?3:1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path v-for="(d,index) in paths[props.name]||paths.note" :key="index" :d="d"/></svg></template>
