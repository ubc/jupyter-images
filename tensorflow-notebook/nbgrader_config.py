from ngshare_exchange import configureExchange

c = get_config()
configureExchange(
    c, 'http://ngshare.default.svc.cluster.local:8080/jupyter/services/ngshare'
)

# Add the following to let students access courses without configuration
# For more information, read Notes for Instructors in the documentation
c.CourseDirectory.course_id = '*'

# Bypass checkpoint files
c.Exchange.exclude = [
    ".ipynb_checkpoints",
    ".ipynb_checkpoints/**",
    "__pycache__",
    "*.pyc",
]
