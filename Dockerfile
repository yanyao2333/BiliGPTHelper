FROM python:3.11-slim-buster as base

WORKDIR /usr/src/app

COPY requirements.txt ./

RUN mkdir -p /clone-data/temp /clone-data/whisper-models /clone-data/queue /clone-data/statistics \
    && touch /clone-data/cache.json

RUN apt-get update \
    && apt-get install -y  ffmpeg fonts-wqy-zenhei \
    && apt-get clean \
    && pip install --no-cache-dir -r requirements.txt

COPY . ./
COPY ./config/docker_config.yml /clone-data/config.yml

ENV CONFIG_FILE=/data/config.yml
ENV CACHE_FILE=/data/cache.json
ENV TEMP_DIR=/data/temp
ENV WHISPER_MODELS_DIR=/data/whisper-models
ENV QUEUE_DIR=/data/queue
ENV RUNNING_IN_DOCKER yes

FROM base as with_whisper
RUN pip install --no-cache-dir openai-whisper

CMD ["python", "main.py"]

FROM base as without_whisper
ENV ENABLE_WHISPER no
CMD ["python", "main.py"]
