# Gunicorn configuration for Ticketing-Intermedic
bind = "0.0.0.0:5000"
workers = 2          # Celery handles background jobs — multiple workers are safe
threads = 4
worker_class = "gthread"
timeout = 120
keepalive = 5
accesslog = "-"
errorlog = "-"
loglevel = "info"
preload_app = True
