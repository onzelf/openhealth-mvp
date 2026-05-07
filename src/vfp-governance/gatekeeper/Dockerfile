FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

RUN pip install --upgrade pip \
  && pip install fastapi uvicorn pydantic

COPY gatekeeper.py /app/gatekeeper.py

EXPOSE 8080

CMD ["uvicorn", "gatekeeper:app", "--host", "0.0.0.0", "--port", "8080"]