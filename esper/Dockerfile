FROM scannerresearch/scanner:cpu
ARG https_proxy
ENV DJANGO_CONFIGURATION Docker
ENV https_proxy=$https_proxy
ENV http_proxy=$https_proxy
ENV TERM=xterm

# Need sudo so Torch can install
RUN apt-get update && apt-get install -y sudo

# Misc apt dependencies
RUN apt-get update && \
    apt-get install -y postgresql libpq-dev cron python-tk sqlite3 \
    npm nodejs curl && \
    ln -s /usr/bin/nodejs /usr/bin/node

# Google Cloud SDK
RUN echo "deb http://packages.cloud.google.com/apt cloud-sdk-xenial main" | \
    tee -a /etc/apt/sources.list.d/google-cloud-sdk.list && \
    curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | apt-key add - && \
    apt-get update && apt-get install -y google-cloud-sdk

# Python dependencies
ADD requirements.txt .
RUN pip install -r requirements.txt && \
    jupyter nbextension enable --py --sys-prefix widgetsnbextension && \
    python -c "import matplotlib"

ENV APPDIR=/usr/src/app
WORKDIR ${APPDIR}

ENV PYTHONPATH=${APPDIR}:${APPDIR}/deps/face_recognizer:${APPDIR}/deps/openface:${APPDIR}/deps/rude-carnie:${APPDIR}/deps/facenet/src:$PYTHONPATH
ENV GLOG_minloglevel=1

# TODO(wcrichto): don't run this if running without --cloud-files
ADD visualdb-key.json .
ENV GOOGLE_APPLICATION_CREDENTIALS=${APPDIR}/visualdb-key.json
RUN gcloud config set project istc-vcs-esper && \
    gcloud auth activate-service-account --key-file=$GOOGLE_APPLICATION_CREDENTIALS

CMD cp .scanner.toml /root/ && gunicorn --log-file=- -c gunicorn_conf.py esper.wsgi:application --reload
