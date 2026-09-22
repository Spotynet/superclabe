"""Configuración de Gunicorn para producción (servidor ASGI con workers Uvicorn)."""
import multiprocessing
import os

bind = "0.0.0.0:8000"
# WEB_CONCURRENCY permite fijar el número de workers desde el entorno.
workers = int(os.getenv("WEB_CONCURRENCY", multiprocessing.cpu_count() * 2 + 1))
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 60
graceful_timeout = 30
keepalive = 5
max_requests = 1000
max_requests_jitter = 100
accesslog = "-"   # stdout
errorlog = "-"    # stderr
loglevel = os.getenv("LOG_LEVEL", "info")
