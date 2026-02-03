FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server code
COPY server/ .

# Expose port
EXPOSE 8080

# Start webhook server with gunicorn for production
CMD ["gunicorn", "webhook_server:app", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "120"]
