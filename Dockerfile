FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=5656

EXPOSE 5656

CMD ["gunicorn", "--bind", "0.0.0.0:5656", "--workers", "2", "--timeout", "30", "app:app"]
