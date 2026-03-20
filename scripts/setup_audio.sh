#!/usr/bin/env bash
set -euo pipefail

if ! pulseaudio --check >/dev/null 2>&1; then
  pulseaudio --start >/dev/null 2>&1
fi

if ! pactl list short sinks | grep -q '^.*call4me_capture[[:space:]]'; then
  pactl load-module module-null-sink \
    sink_name=call4me_capture \
    sink_properties=device.description=Call4Me_Capture >/dev/null
fi

if ! pactl list short sinks | grep -q '^.*call4me_tts[[:space:]]'; then
  pactl load-module module-null-sink \
    sink_name=call4me_tts \
    sink_properties=device.description=Call4Me_TTS >/dev/null
fi

if ! pactl list short sources | grep -q '^.*call4me_mic[[:space:]]'; then
  pactl load-module module-remap-source \
    master=call4me_tts.monitor \
    source_name=call4me_mic \
    source_properties=device.description=Call4Me_Microphone >/dev/null
fi

pactl set-default-sink call4me_capture
pactl set-default-source call4me_mic
