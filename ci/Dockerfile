FROM python:3.11-slim-buster as base

WORKDIR /usr/src/app

COPY ../requirements.txt ./

RUN mkdir -p /clone-data/temp /clone-data/whisper-models /clone-data/statistics \
    && touch /clone-data/cache.json && touch /clone-data/records.json && touch /clone-data/queue.json

RUN apt-get update \
#    && apt-get install -y  ffmpeg fonts-wqy-zenhei \
    && apt-get install -y ffmpeg  \
    && apt-get clean \
    && pip install --no-cache-dir -r requirements.txt

COPY .. ./
COPY ../config/docker_config.yml /clone-data/config.yml

ENV DOCKER_CONFIG_FILE=/data/config.yml
ENV DOCKER_CACHE_FILE=/data/cache.json
ENV DOCKER_TEMP_DIR=/data/temp
ENV DOCKER_WHISPER_MODELS_DIR=/data/whisper-models
ENV DOCKER_QUEUE_DIR=/data/queue.json
ENV DOCKER_RECORDS_DIR=/data/records.json
ENV DOCKER_STATISTICS_DIR=/data/statistics
ENV RUNNING_IN_DOCKER yes

FROM base as with_whisper
ENV ENABLE_WHISPER yes
RUN pip install --no-cache-dir openai-whisper

CMD ["python", "main.py"]

FROM base as without_whisper
ENV ENABLE_WHISPER no
CMD ["python", "main.py"]
