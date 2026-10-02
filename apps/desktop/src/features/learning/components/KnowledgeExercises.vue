<script setup lang="ts">
import type {AnswerRow} from '../composables/useCourseAnswers'
import {navigate, statusLabel} from '../../../shared/ui'
defineProps<{rows: AnswerRow[]; blocked: boolean}>()
</script>

<template>
  <section class="knowledge-exercises" aria-label="当前知识点练习">
    <header class="practice-heading"><span class="eyebrow accent">学以致用</span><h3>把理解写下来</h3><p class="muted small">可以暂时跳过，最后统一提交本课答案。</p></header>
    <article v-for="(row,i) in rows" :key="row.exercise_id" class="knowledge-question" :data-exercise="row.exercise_id">
      <header class="question-heading"><span class="question-index">{{String(i+1).padStart(2,'0')}}</span><h4>{{row.title}}</h4><span v-if="row.submission" :class="['status-chip',row.submission.status.toLowerCase()]">{{statusLabel(row.submission.status)}}</span><span v-else class="muted small">{{row.answer.trim() ? '有草稿' : '未作答'}}</span></header>
      <p class="exercise-prompt">{{row.prompt}}</p>
      <details v-if="row.requirements" class="question-requirements"><summary>作答要求</summary><p>{{row.requirements}}</p></details>
      <div v-if="row.submission" class="inline-feedback"><p v-if="!row.submission.study_session_id" class="muted small">历史作答未保存当时材料快照，不能把本轮题面视为其原始题面。</p>
        <details :open="row.action !== 'LOCKED'"><summary>{{row.action==='LOCKED' ? '我的已提交答案' : '上次提交的原答案'}}</summary><pre class="answer-text">{{row.submission.answer_text}}</pre></details>
        <section v-for="review in row.submission.reviews" :key="review.id" class="inline-review"><strong>{{review.summary}}</strong><div v-if="review.rendered_html" class="markdown-body" v-html="review.rendered_html"/><p class="review-next-action">下一步：{{review.next_action || row.submission.next_action}}</p></section>
        <p v-if="!row.submission.reviews.length" class="waiting-note">等待外部 Agent 批改，不影响继续学习其他课程。</p>
        <button class="text-button history-link" @click="navigate('/submission/'+row.submission!.id)">查看这道题的历史 ↗</button>
      </div>
      <template v-if="row.action !== 'LOCKED'">
        <label :for="'answer-'+row.exercise_id" class="answer-label">{{row.action==='REVISION'?'本次修正版':row.action==='RETEST'?'复测答案（按反馈中的复测题作答）':'我的答案'}}<span>{{row.answer.length}} 字</span></label>
        <textarea :id="'answer-'+row.exercise_id" v-model="row.answer" :disabled="blocked" rows="7" placeholder="写下你的理解、推导或代码。下一步会自动保存。" spellcheck="false"/>
      </template>
    </article>
    <p v-if="!rows.length" class="muted">这个知识点没有练习，确认读完后继续即可。</p>
  </section>
</template>
