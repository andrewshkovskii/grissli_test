FROM ubuntu:16.04
RUN apt-get update -y\
  && apt-get install -y python3 python3-pip \
  && apt-get install -y nodejs npm \
  && apt-get install -y git \
  && apt-get clean \
  && apt-get autoremove \
  && rm -rf /tmp/* /var/tmp/*
RUN ln -s /usr/bin/nodejs /usr/bin/node \
    && npm install bower -g
COPY . /opt/grissli_test/
WORKDIR /opt/grissli_test/
RUN bower install --allow-root \
    && pip3 install -r /opt/grissli_test/requirements.txt --no-cache-dir