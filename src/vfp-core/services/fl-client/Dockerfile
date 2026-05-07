FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# CPU-only PyTorch, Flower, MedMNIST, and support libraries.
RUN pip install --upgrade pip \
  && pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu \
  && pip install flwr medmnist pandas requests numpy

COPY client.py /app/client.py

CMD ["python", "client.py"]