ARG PYTHON_VERSION=3
ARG ALPINE_VERSION=
FROM python:${PYTHON_VERSION}-alpine${ALPINE_VERSION}

COPY ./dist /opt/vmn_wheel

RUN apk add --no-cache git openssh && \
  pip install /opt/vmn_wheel/*.whl

ENTRYPOINT ["/usr/local/bin/vmn"]
