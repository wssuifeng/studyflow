from __future__ import annotations
from datetime import date, time
from sqlalchemy import select
from studyflow.modules.courses.models import Course, Exercise, Lesson
from studyflow.modules.planning.models import CourseScheduleItem, PlanLine, Stage, Task, TimeBlock
from studyflow.shared.ids import new_id
from studyflow.modules.planning.repository import ensure_course_membership


from studyflow.infrastructure.runtime import Runtime, Service


class DemoService(Service):
    def seed_demo(self, target_date: date | None = None) -> dict:
        target_date = target_date or date.today()
        lesson_specs = [
            (
                "\u5bf9\u8c61\u3001\u5f15\u7528\u4e0e\u65b9\u6cd5\u8c03\u7528",
                "\u628a\u8bed\u8a00\u8bed\u4e49\u3001JVM \u62bd\u8c61\u548c\u5b9e\u73b0\u76f4\u89c9\u5206\u5f00\u3002",
                "\u7528\u81ea\u5df1\u7684\u8bdd\u89e3\u91ca\u5f15\u7528\u503c\u526f\u672c\u4e0e\u5bf9\u8c61\u5b57\u6bb5\u4fee\u6539\u3002",
                "\u8bf7\u89e3\u91ca\uff1a\u8c03\u7528 device.updateStatus() \u540e\uff0c\u4e3a\u4ec0\u4e48\u8c03\u7528\u65b9\u770b\u5230 device.status \u53d1\u751f\u53d8\u5316\uff1f\u540c\u65f6\u8bf4\u660e Java \u662f\u5426\u5b58\u5728\u53ef\u76f4\u63a5\u8fdb\u884c\u6307\u9488\u8fd0\u7b97\u7684\u6307\u9488\u3002",
                "\u81f3\u5c11\u5199\u51fa\uff1a\u503c\u4f20\u9012\u3001\u5f15\u7528\u503c\u526f\u672c\u3001\u540c\u4e00\u5bf9\u8c61\u5b57\u6bb5\u3001\u4e0d\u80fd\u8fdb\u884c\u5730\u5740\u8fd0\u7b97\u56db\u4e2a\u8981\u70b9\u3002",
            ),
            (
                "equals \u4e0e hashCode \u5951\u7ea6",
                "\u7406\u89e3\u5bf9\u8c61\u76f8\u7b49\u5224\u65ad\u4e0e\u54c8\u5e0c\u96c6\u5408\u884c\u4e3a\u4e4b\u95f4\u7684\u7ea6\u675f\u3002",
                "\u8bf4\u660e equals/hashCode \u7684\u4e00\u81f4\u6027\u3002",
                "\u8bf7\u8bf4\u660e\u91cd\u5199 equals \u540e\u4e3a\u4ec0\u4e48\u901a\u5e38\u4e5f\u5fc5\u987b\u91cd\u5199 hashCode\uff0c\u5e76\u4e3e\u51fa\u653e\u5165 HashSet \u7684\u5f71\u54cd\u3002",
                "\u81f3\u5c11\u5199\u51fa\uff1a\u76f8\u7b49\u5bf9\u8c61\u5fc5\u987b\u62e5\u6709\u76f8\u540c hashCode\u3001HashSet \u67e5\u627e\u4f9d\u8d56\u4e24\u8005\u3001\u7834\u574f\u5951\u7ea6\u7684\u540e\u679c\u3002",
            ),
            (
                "\u5f02\u5e38\u94fe\u4e0e\u7edf\u4e00\u9519\u8bef\u5904\u7406",
                "\u7406\u89e3\u5f02\u5e38\u5305\u88c5\u3001\u6839\u56e0\u4fdd\u7559\u548c\u7edf\u4e00\u5904\u7406\u8fb9\u754c\u3002",
                "\u8bbe\u8ba1\u4e00\u4e2a\u53ef\u8ffd\u8e2a\u6839\u56e0\u7684\u5f02\u5e38\u5904\u7406\u65b9\u6848\u3002",
                "\u8bf7\u89e3\u91ca\u4e3a\u4ec0\u4e48\u4e1a\u52a1\u5c42\u4e0d\u5e94\u53ea\u629b\u51fa\u4e00\u4e2a\u4e22\u5931\u6839\u56e0\u7684\u901a\u7528\u5f02\u5e38\uff0c\u4ee5\u53ca\u5982\u4f55\u4fdd\u7559 cause \u5e76\u5728\u8fb9\u754c\u7edf\u4e00\u8f6c\u6362\u3002",
                "\u81f3\u5c11\u5199\u51fa\uff1a\u539f\u59cb cause\u3001\u5f02\u5e38\u8fb9\u754c\u3001\u7528\u6237\u53ef\u8bfb\u9519\u8bef\u3001\u65e5\u5fd7\u8ffd\u8e2a\u56db\u4e2a\u8981\u70b9\u3002",
            ),
        ]
        with self.session() as db:
            existing = db.scalar(select(PlanLine).where(PlanLine.name.like("Java%")))
            if existing:
                existing.name = "Java\u5c31\u4e1a"
                course = db.scalar(select(Course).where(Course.plan_line_id == existing.id, Course.title.like("Java%")))
                if not course:
                    course = db.scalar(select(Course).where(Course.plan_line_id == existing.id).order_by(Course.created_at))
                if course:
                    course.title = "Java\u5bf9\u8c61\u6a21\u578b\uff1a\u4ece\u5f15\u7528\u5230\u8fd0\u884c\u8fc7\u7a0b"
                    course.summary = "\u7528\u591a\u4e2a\u77e5\u8bc6\u70b9\u548c\u53ef\u8fd0\u884c\u7684\u5c0f\u7ec3\u4e60\u7406\u89e3\u5bf9\u8c61\u3001\u5f15\u7528\u3001\u5951\u7ea6\u4e0e\u5f02\u5e38\u8fb9\u754c\u3002"
                    item = ensure_course_membership(db, existing, course)
                    existing_lessons = sorted(course.lessons, key=lambda lesson: lesson.position)
                    for position, (title, summary, exercise_title, prompt, requirements) in enumerate(lesson_specs, start=1):
                        lesson = existing_lessons[position - 1] if position <= len(existing_lessons) else None
                        if lesson is None:
                            lesson = Lesson(id=new_id(), course_id=course.id, title=title, position=position, markdown_path="content/lessons/java-reference.md", summary=summary)
                            db.add(lesson)
                        lesson.title = title
                        lesson.position = position
                        lesson.summary = summary
                        lesson.markdown_path = "content/lessons/java-reference.md"
                        if lesson.exercises:
                            exercise = sorted(lesson.exercises, key=lambda item: item.position)[0]
                            exercise.title = exercise_title
                            exercise.prompt = prompt
                            exercise.requirements = requirements
                        else:
                            lesson.exercises.append(Exercise(id=new_id(), title=exercise_title, position=1, prompt=prompt, requirements=requirements))
                    if not db.scalar(select(CourseScheduleItem).where(CourseScheduleItem.plan_course_item_id == item.id, CourseScheduleItem.scheduled_date == target_date)):
                        db.add(CourseScheduleItem(id=new_id(), plan_course_item_id=item.id, scheduled_date=target_date, position=1, start_time=time(9, 0), end_time=time(10, 30)))
                return {"created": False, "plan_line_id": existing.id, "course_id": course.id if course else None}
            plan = PlanLine(id=new_id(), name="Java\u5c31\u4e1a", priority=1)
            stage = Stage(id=new_id(), plan_line=plan, name="StudyFlow\u4ea7\u54c1\u7b2c\u4e00\u6761\u95ed\u73af", window_start=target_date, window_end=target_date)
            task = Task(id=new_id(), stage=stage, title="\u5b8c\u6210 StudyFlow \u7b2c\u4e00\u8282\u8bfe\u7a0b\u4e0e\u7ec3\u4e60", description="\u9605\u8bfb\u8bfe\u7a0b\uff0c\u5b8c\u6210\u7ec3\u4e60\u5e76\u63d0\u4ea4\u7b54\u6848\uff0c\u4e4b\u540e\u7531\u5916\u90e8 Agent \u901a\u8fc7 CLI \u6279\u6539\u3002", scheduled_date=target_date, priority=1, task_kind="PRACTICE")
            task.time_blocks.append(TimeBlock(id=new_id(), block_date=target_date, start_time=time(9, 0), end_time=time(10, 30)))
            course = Course(id=new_id(), plan_line=plan, title="Java\u5bf9\u8c61\u6a21\u578b\uff1a\u4ece\u5f15\u7528\u5230\u8fd0\u884c\u8fc7\u7a0b", summary="\u7528\u591a\u4e2a\u77e5\u8bc6\u70b9\u548c\u53ef\u8fd0\u884c\u7684\u5c0f\u7ec3\u4e60\u7406\u89e3\u5bf9\u8c61\u3001\u5f15\u7528\u3001\u5951\u7ea6\u4e0e\u5f02\u5e38\u8fb9\u754c\u3002")
            for position, (title, summary, exercise_title, prompt, requirements) in enumerate(lesson_specs, start=1):
                lesson = Lesson(id=new_id(), course=course, title=title, position=position, markdown_path="content/lessons/java-reference.md", summary=summary)
                lesson.exercises.append(Exercise(id=new_id(), title=exercise_title, position=1, prompt=prompt, requirements=requirements))
            db.add(plan)
            db.flush()
            item = ensure_course_membership(db, plan, course)
            schedule = CourseScheduleItem(id=new_id(), plan_course_item_id=item.id, scheduled_date=target_date, position=1, start_time=time(9, 0), end_time=time(10, 30))
            task.course_schedule_item_id = schedule.id
            db.add(schedule)
            self._event(db, "SYSTEM_JOB", "course", course.id, "SEED_DEMO", "\u521b\u5efa\u591a\u77e5\u8bc6\u70b9\u6f14\u793a\u8bfe\u7a0b\u95ed\u73af")
            return {"created": True, "plan_line_id": plan.id, "task_id": task.id, "course_id": course.id, "exercise_id": course.lessons[0].exercises[0].id}
