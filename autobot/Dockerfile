FROM python:3.12-slim
WORKDIR /opt/autobot
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && mkdir /data && chown 10001:10001 /data
COPY app ./app
COPY deploy/configure_matrix.py ./deploy/
USER 10001:10001
CMD ["uvicorn", "app.web_app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-proxy-headers", "--no-access-log"]
