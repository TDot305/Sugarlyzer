FROM sugarlyzer/base

RUN apt-get update -y \
    && apt-get install -y unzip openjdk-21-jdk

ADD https://github.com/joernio/joern/releases/latest/download/joern-install.sh /joern-install.sh
WORKDIR /
RUN chmod +x joern-install.sh \
    && /joern-install.sh --version 2.0.400 \
    && rm /joern-install.sh /joern-cli.zip
ENV PATH="/opt/joern/joern-cli:${PATH}"
RUN joern-scan --updatedb