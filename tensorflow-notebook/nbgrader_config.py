import os

from ngshare_exchange import configureExchange

c = get_config()
configureExchange(
    c, 'http://ngshare.default.svc.cluster.local:8080/services/ngshare'
)

# Set by the Hub's 21-nbgrader-course-id-env pre_spawn_hook, from the
# instructor's formgrade-<course_id> group AND confirmed to exist in
# ngshare's own DB. Students, and instructors with zero or multiple
# currently-active courses, fall back to "*" (nbgrader's documented
# student-only convenience).
c.CourseDirectory.course_id = os.environ.get("NBGRADER_COURSE_ID", "*")
