FROM python:3.12-alpine

# Build deps for Pillow
RUN apk add --no-cache \
    gcc musl-dev libffi-dev \
    jpeg-dev zlib-dev freetype-dev \
    ttf-dejavu

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

# Uploads dir (mapped to named volume in compose)
RUN mkdir -p /app/uploads && chmod 777 /app/uploads

EXPOSE 8000

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "30", "app:app"]
