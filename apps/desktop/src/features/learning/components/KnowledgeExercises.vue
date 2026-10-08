<script setup lang="ts">
import {computed} from 'vue'
import {isTauri} from '../../../shared/api'
import {getCurrentWindow} from '@tauri-apps/api/window'
import {emitTo} from '@tauri-apps/api/event'
import type {AnswerRow} from '../composables/useCourseAnswers'
import {navigate} from '../../../shared/ui'
const props=defineProps<{rows: AnswerRow[]; blocked: boolean}>()
const answeredCount=computed(()=>props.rows.filter(row=>row.answer.trim()).length)
const submittedCount=computed(()=>props.rows.filter(row=>!!row.submission).length)
const feedbackCount=computed(()=>props.rows.filter(row=>(row.submission?.reviews?.length||0)>0).length)
function answerHint(row: AnswerRow) {
 if (row.action==='WAITING_RETEST_TASK') return '等待新的复测题'
 if (row.action==='RETEST') return '正在完成复测'
 if (row.action==='REVISION') return '正在完成修正版'
 if (row.submission) return '本题已有提交记录'
 return row.answer.trim() ? '草稿会自动保存' : '可以暂时跳过'
}
function submissionHint(row: AnswerRow) {
 const status=row.submission?.status||''
 if (status==='PASSED') return '本题已通过，历史答案与批改记录仍可查看。'
 if (row.action==='WAITING_RETEST_TASK') return '批改已要求复测，等待外部 Agent 发布并冻结新的复测题。'
 if (row.action==='RETEST') return '请完成独立复测题；本次作答不会覆盖原答案。'
 if (row.action==='REVISION' || ['NEEDS_REVISION','REVISION_REQUIRED'].includes(status)) return '请根据批改意见提交修正版，原答案会继续保留。'
 if (['WAITING_REVIEW','REVIEWED','RECHECKED','PARTIAL_FEEDBACK'].includes(status)) return '已提交本轮答案，等待或查看外部 Agent 的批改反馈。'
 if (row.submission) return '本题已有提交记录，可以继续查看批改或历史版本。'
 return row.answer.trim() ? '当前内容为本地草稿，下一步会自动保存。' : '尚未作答，可以先跳过，之后再回到本题。'
}
async function openHistory(id:string) {
 if(isTauri()&&getCurrentWindow().label.startsWith('tool-'))await emitTo('main','studyflow-open-feedback',{id})
 else await navigate('/submission/'+id)
}
</script>

<template>
  <section class="knowledge-exercises" aria-label="当前知识点练习">
    <header class="practice-heading">
      <div><span class="eyebrow accent">学以致用</span><h3>把理解写下来</h3><p class="muted small">可以暂时跳过，最后统一提交本课答案。</p></div>
      <div class="practice-summary" aria-label="本知识点作答摘要"><span><strong>{{rows.length}}</strong> 道题</span><span><strong>{{answeredCount}}</strong> 已填写</span><span><strong>{{submittedCount}}</strong> 已提交</span><span v-if="feedbackCount"><strong>{{feedbackCount}}</strong> 有反馈</span></div>
    </header>
    <article v-for="(row,i) in rows" :key="row.exercise_id" class="knowledge-question" :data-exercise="row.exercise_id">
      <header class="question-heading">
        <div class="question-index-block"><span class="question-index">{{String(i+1).padStart(2,'0')}}</span><span class="question-type">练习题</span></div>
        <div class="question-title"><h4>{{row.title}}</h4><span class="question-meta">{{answerHint(row)}}</span></div>
      </header>
      <div class="exercise-prompt-wrap"><span class="exercise-prompt-label">题目</span><p class="exercise-prompt">{{row.prompt}}</p></div>
      <div v-if="row.requirements" class="question-requirements-box"><strong>作答要求</strong><p>{{row.requirements}}</p></div>
      <p v-if="row.action==='WAITING_RETEST_TASK'" class="waiting-note exercise-action-note">等待 Agent 发布复测题；不用猜评语里的题面。</p>
      <p v-if="row.retest_task" class="retest-objective">复测目标：{{row.retest_task.objective}} · 题面已冻结</p>
      <div v-if="row.submission" class="inline-feedback">
        <p v-if="!row.submission.study_session_id" class="muted small">历史作答未保存当时材料快照，不能把本轮题面视为其原始题面。</p>
        <p class="exercise-action-note">{{submissionHint(row)}}</p>
        <details :open="!['LOCKED','WAITING_RETEST_TASK'].includes(row.action)"><summary>{{row.action==='LOCKED' ? '我的已提交答案' : '上次提交的原答案'}}</summary><pre class="answer-text">{{row.submission.answer_text}}</pre></details>
        <section v-for="review in row.submission.reviews" :key="review.id" class="inline-review"><strong>{{review.summary}}</strong><section v-for="(issue,i) in review.issues||[]" :key="i" class="review-issue"><blockquote>{{issue.quote}}</blockquote><small>{{issue.location}}</small><p><strong>原因</strong> {{issue.reason}}</p><p><strong>正确方向</strong> {{issue.guidance}}</p><p><strong>下一步</strong> {{issue.next_action}}</p></section><div v-if="review.rendered_html" class="markdown-body" v-html="review.rendered_html"/><p class="review-next-action">下一步：{{review.next_action || row.submission.next_action}}</p></section>
        <p v-if="!row.submission.reviews.length" class="waiting-note">等待外部 Agent 批改，不影响继续学习其他课程。</p>
        <button class="text-button history-link" @click="openHistory(row.submission!.id)">查看这道题的历史 ↗</button>
      </div>
      <template v-if="!['LOCKED','WAITING_RETEST_TASK'].includes(row.action)">
        <label :for="'answer-'+row.exercise_id" class="answer-label">{{row.action==='REVISION'?'本次修正版':row.action==='RETEST'?'本次新题复测答案':'我的答案'}}<span>{{row.answer.length}} 字</span></label>
        <textarea :id="'answer-'+row.exercise_id" v-model="row.answer" :disabled="blocked" rows="7" placeholder="写下你的理解、推导或代码。下一步会自动保存。" spellcheck="false"/>
        <footer class="question-footer"><span class="answer-save-hint">{{row.answer.trim()?'草稿已进入自动保存队列':'暂未填写，可先跳过'}}</span><span>{{row.answer.length}} / 建议完整表达</span></footer>
      </template>
    </article>
    <p v-if="!rows.length" class="muted">这个知识点没有练习，确认读完后继续即可。</p>
  </section>
</template>
