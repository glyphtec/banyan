FROM python:3.12-slim

WORKDIR /app
COPY backend /app/backend
RUN pip install --no-cache-dir -e /app/backend

WORKDIR /app/backend
EXPOSE 8000
CMD ["python", "-m", "banyan_platform.main"]
