FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

RUN pip install --upgrade pip \
  && pip install fastapi uvicorn pydantic requests

COPY hub.py /app/hub.py

EXPOSE 8080

CMD ["uvicorn", "hub:app", "--host", "0.0.0.0", "--port", "8080"]