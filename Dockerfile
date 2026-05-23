# Stage 1: Build Tailwind CSS (node only — not shipped to prod)
FROM node:20-alpine AS css-builder
WORKDIR /build
COPY package.json tailwind.config.js ./
RUN npm install
# Copy only what Tailwind needs to scan: templates + input CSS
COPY app/templates ./app/templates
COPY app/static/css/tailwind.in.css ./app/static/css/tailwind.in.css
RUN npm run build:css

# Stage 2: Production image (no nodejs/npm)
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps (cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY . .

# Overlay the pre-built CSS from stage 1
COPY --from=css-builder /build/app/static/css/tailwind.css ./app/static/css/tailwind.css

ENV USE_BUNDLED_CSS=true

RUN useradd -m appuser && chown -R appuser /app
USER appuser

EXPOSE 5000

CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
