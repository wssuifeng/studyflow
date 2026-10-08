export function courseAction(course:{study_status?:string;learning_submitted?:boolean}){
 const state=course.study_status||'NOT_STARTED'
 return state==='NEEDS_REVISION'?'修正答案':state==='RETEST_REQUIRED'?'查看复测':state==='PARTIAL_FEEDBACK'?'查看新反馈':state==='WAITING_REVIEW'?'等待批改 · 回看':state==='PASSED'?'回顾已通过课程':state==='NOT_STARTED'?'开始学习':'继续学习'
}
