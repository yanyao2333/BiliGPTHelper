FROM python:3.11-slim-buster

WORKDIR /usr/src/app

COPY requirements.txt ./

RUN mkdir -p /clone-data/temp /clone-data/whisper-models /clone-data/queue \
    && touch /clone-data/cache.json \
    && apt-get update \
    && apt-get install -y  ffmpeg \
    && apt-get clean \
    && pip install --no-cache-dir -r requirements.txt

COPY . ./
COPY config.yml /clone-data/config.yml

ENV CONFIG_FILE=/data/config.yml
ENV CACHE_FILE=/data/cache.json
ENV TEMP_DIR=/data/temp
ENV WHISPER_MODELS_DIR=/data/whisper-models
ENV QUEUE_DIR=/data/queue
ENV RUNNING_IN_DOCKER yes

CMD ["python", "main.py"]
