import type {JSONContent} from '@tiptap/core'
import {groupEntries, entryFromScope, visibleEntries, type Entry, type Course, type Scope, type RichNode} from './model'

const card = (entry:Entry):JSONContent => ({
  type:'noteCard',
  attrs:{entryId:entry.id,scope:entry.scope,courseId:entry.courseId,lessonId:entry.lessonId},
  content:entry.content,
})

// Metadata may arrive after the notes or refer to an archived course. Preserve
// the saved identity/title while still accepting current metadata when present.
function contextualCourses(entries:Entry[], courses:Course[], scope:Scope):Course[] {
  const result = courses.map(course=>({...course,lessons:[...course.lessons]}))
  for (const entry of entries) {
    if (!entry.courseId) continue
    let course = result.find(value=>value.id===entry.courseId)
    if (!course) {
      course={id:entry.courseId,title:entry.courseTitle||'历史课程',lessons:[]}
      result.push(course)
    }
    if (entry.lessonId&&!course.lessons.some(lesson=>lesson.id===entry.lessonId)) {
      course.lessons.push({id:entry.lessonId,title:entry.lessonTitle||'历史知识点'})
    }
  }
  if (scope.mode!=='PLAN'&&scope.courseId) {
    let course=result.find(value=>value.id===scope.courseId)
    if (!course) {
      course={id:scope.courseId,title:'当前课程',lessons:[]}
      result.push(course)
    }
    if (scope.mode==='LESSON'&&scope.lessonId&&!course.lessons.some(lesson=>lesson.id===scope.lessonId)) {
      course.lessons.push({id:scope.lessonId,title:'当前知识点'})
    }
  }
  return result
}

export function toProjection(entries:Entry[], courses:Course[], scope:Scope, collapsed:Set<string>, emptyEntry?:Entry):JSONContent {
  const visible=visibleEntries(entries,scope)
  const projected=visible.length?visible:[emptyEntry||entryFromScope(scope)]
  const groups=groupEntries(projected,contextualCourses(projected,courses,scope))
  return {
    type:'doc',
    content:groups.map(course=>{
      const courseKey='course:'+course.id
      return {
        type:'courseGroup',
        attrs:{groupId:course.id,title:course.title,collapsed:collapsed.has(courseKey),foldKey:courseKey},
        content:collapsed.has(courseKey)?[]:course.lessons.map(lesson=>{
          const lessonKey='lesson:'+course.id+':'+lesson.id
          return {
            type:'lessonGroup',
            attrs:{groupId:lesson.id,title:lesson.title,collapsed:collapsed.has(lessonKey),foldKey:lessonKey},
            content:collapsed.has(lessonKey)?[]:lesson.entries.map(card),
          }
        }),
      }
    }),
  }
}

export function entriesFromProjection(doc:JSONContent):Entry[] {
  const output:Entry[]=[]
  function walk(node:JSONContent) {
    if (node.type==='noteCard') {
      output.push({id:node.attrs?.entryId,scope:node.attrs?.scope,courseId:node.attrs?.courseId||null,
        lessonId:node.attrs?.lessonId||null,content:node.content as RichNode[]||[{type:'paragraph'}]})
    } else node.content?.forEach(walk)
  }
  walk(doc)
  return output
}
