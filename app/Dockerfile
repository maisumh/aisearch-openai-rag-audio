# Stage 1: Vite build
FROM node:20-slim AS build-stage
WORKDIR /app/frontend
COPY frontend/ ./
RUN npm install
RUN npm run build

# Stage 2: Python backend with static
FROM python:3.12-slim AS production-stage
WORKDIR /app
COPY backend/ /app
COPY --from=build-stage /app/frontend/dist /app/static

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN pip install -r requirements.txt
RUN pip install gunicorn

CMD ["python3", "-m", "gunicorn", "app:create_app", "-b", "0.0.0.0:8000", "--worker-class", "aiohttp.GunicornWebWorker"]