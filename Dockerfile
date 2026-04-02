FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/database

# Inicia servidor Flask com Gunicorn
exec gunicorn --bind 0.0.0.0:8000 --workers 1 --worker-class sync --timeout 120 main:app' > /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh

# O container agora roda o script de boot
CMD ["/app/entrypoint.sh"]