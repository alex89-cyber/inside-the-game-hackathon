FROM python:3.12-slim

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY simulator ./simulator
COPY insights ./insights
COPY agents ./agents
COPY app ./app

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
USER 1000
CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
