ARG BUILD_FROM
FROM $BUILD_FROM

ENV LANG C.UTF-8

# Install requirements for python scripts
RUN \
  apk add --no-cache \
    python3 \
    py3-pip \
    py3-pillow \
    py3-websockets \
    py3-aiohttp

# Copy data for add-on
COPY run.sh /
COPY ha_billboard.py /
COPY listener.py /

RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
