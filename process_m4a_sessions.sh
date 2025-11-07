#!/usr/bin/env bash

# usage: ./process_m4a.sh [directory]
DIR="${1:-.}"

# rnnoise model name we'll use inside the directory
MODEL_NAME="std.rnnn"
MODEL_PATH="${DIR}/${MODEL_NAME}"

# 1. make sure the model exists
if [ ! -f "$MODEL_PATH" ]; then
  echo "rnnoise model not found in $DIR, downloading..."
  # this is a public set of arnndn models for ffmpeg
  curl -L -o "$MODEL_PATH" \
    https://raw.githubusercontent.com/richardpl/arnndn-models/master/std.rnnn

  if [ $? -ne 0 ]; then
    echo "Failed to download rnnoise model. Exiting."
    exit 1
  fi
else
  echo "Found existing rnnoise model at $MODEL_PATH"
fi

# 2. process every .m4a in the directory
shopt -s nullglob
for f in "$DIR"/*.m4a; do
  base="$(basename "$f" .m4a)"
  out="${DIR}/${base}_processed.wav"

  echo "Processing: $f -> $out"

  # Note: volume=normalize is not a valid expression in ffmpeg 8.0; using dynaudnorm for adaptive loudness normalization.
  # Filter order: clean (hp/lp) -> denoise -> adaptive loudness -> compression.
  ffmpeg -y -i "$f" \
    -ac 1 -ar 16000 \
    -af "highpass=f=80,lowpass=f=8000,arnndn=m=${MODEL_PATH},dynaudnorm=f=150:g=15,acompressor=threshold=-21dB:ratio=3:attack=100:release=500" \
    "$out"
done
shopt -u nullglob

echo "Done."
