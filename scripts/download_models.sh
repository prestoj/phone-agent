#!/usr/bin/env bash
# Fetch the Kokoro TTS model + voices file used by the receptionist.
# About 350 MB total. Idempotent — skips if files already present.
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p models
cd models

MODEL_URL="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
VOICES_URL="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"

if [[ -f kokoro-v1.0.onnx ]]; then
    echo "kokoro-v1.0.onnx already present"
else
    echo "Downloading kokoro-v1.0.onnx (~326 MB)…"
    curl -L --progress-bar -o kokoro-v1.0.onnx "$MODEL_URL"
fi

if [[ -f voices-v1.0.bin ]]; then
    echo "voices-v1.0.bin already present"
else
    echo "Downloading voices-v1.0.bin (~28 MB)…"
    curl -L --progress-bar -o voices-v1.0.bin "$VOICES_URL"
fi

echo "Done. Files in $(pwd):"
ls -lh kokoro-v1.0.onnx voices-v1.0.bin

# Parakeet model is auto-downloaded by parakeet-mlx on first transcribe.
