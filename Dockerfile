FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --requirement /app/requirements.txt
COPY app.py /app/app.py
COPY templates /app/templates
EXPOSE 8099
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8099", "--no-access-log"]
