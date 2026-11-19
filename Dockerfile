FROM python:3.12-slim

# ffmpeg does all the cutting/rendering; fonts-dejavu-core gives the caption renderer a usable font.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# README.md is required: pyproject.toml uses it as the package readme.
COPY pyproject.toml README.md ./
COPY primeclips ./primeclips

# No optional extras by default. Add some with:
#   docker build --build-arg EXTRAS=all .          (captions + YouTube chat + YouTube upload)
#   docker build --build-arg EXTRAS=captions .
ARG EXTRAS=""
RUN if [ -n "$EXTRAS" ]; then pip install --no-cache-dir ".[${EXTRAS}]"; else pip install --no-cache-dir .; fi

VOLUME /data
ENV PRIMECLIPS_DATA_DIR=/data

EXPOSE 8765
CMD ["primeclips", "serve", "--host", "0.0.0.0"]
