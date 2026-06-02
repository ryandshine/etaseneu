# Stage 1: Build Frontend
FROM node:20-alpine AS build-frontend
WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-update-notifier

COPY frontend /app/frontend
RUN npm run build --no-update-notifier

# Stage 2: Final Image (Python + Nginx)
FROM python:3.11-slim

# Install Nginx and Supervisor
RUN apt-get update && \
    apt-get install -y nginx supervisor && \
    rm -rf /var/lib/apt/lists/*

# Setup Python Backend
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app/backend
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY backend /app/backend
RUN mkdir -p /app/shp

# Setup Frontend Nginx
COPY --from=build-frontend /app/frontend/dist /usr/share/nginx/html

# Copy Nginx config and replace 'api' host with '127.0.0.1' since both run in the same container
COPY deploy/nginx/etaseneu.conf /etc/nginx/conf.d/default.conf
RUN sed -i 's/http:\/\/api:8000/http:\/\/127.0.0.1:8000/g' /etc/nginx/conf.d/default.conf

# Remove default nginx site if exists to prevent conflicts
RUN rm -f /etc/nginx/sites-enabled/default

# Setup Supervisor to run both Nginx and Uvicorn
RUN echo "[supervisord]\n\
nodaemon=true\n\
\n\
[program:api]\n\
command=uvicorn app.main:app --host 127.0.0.1 --port 8000\n\
directory=/app/backend\n\
autostart=true\n\
autorestart=true\n\
stdout_logfile=/dev/stdout\n\
stdout_logfile_maxbytes=0\n\
stderr_logfile=/dev/stderr\n\
stderr_logfile_maxbytes=0\n\
\n\
[program:nginx]\n\
command=nginx -g 'daemon off;'\n\
autostart=true\n\
autorestart=true\n\
stdout_logfile=/dev/stdout\n\
stdout_logfile_maxbytes=0\n\
stderr_logfile=/dev/stderr\n\
stderr_logfile_maxbytes=0" > /etc/supervisor/conf.d/supervisord.conf

EXPOSE 80

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
