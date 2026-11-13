# Gunicorn configuration for Ticketing-Intermedic
bind = "0.0.0.0:5000"
workers = 2          # Celery handles background jobs — multiple workers are safe
threads = 4
worker_class = "gthread"
timeout = 120
keepalive = 5
accesslog = "-"
# Default format plus rt= (seconds spent inside gunicorn). If rt is small but the browser
# still spins, the time is being lost between nginx and the browser, not in the app.
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" rt=%(L)s'
errorlog = "-"
loglevel = "info"
preload_app = True
