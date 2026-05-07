FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

RUN pip install --upgrade pip \
  && pip install flwr numpy pandas

COPY server.py /app/server.py

EXPOSE 8080

CMD ["python", "server.py"]