# Call4Me

Call4Me is an automated AI phone assistant that connects to Google Voice via headed Chromium and PulseAudio to dial phone numbers, process audio (STT), generate responses (LLM), and playback synthesized voice (TTS).

## Features

- **Automated Call Navigation**: Navigates complicated IVR phone trees by understanding voice prompts and pressing keys automatically.
- **Auto-Learning Memory System**: Learns and stores IVR maps, strategies, and conversation tips locally in SQLite to navigate menus faster in future calls.
- **Local AI Pipeline**: Runs entirely on local models using Faster-Whisper (STT), Piper (TTS), and Chat2API (LLM interface).
- **Flexible Tasks**: Supports custom prompts for booking flights, inquiring about prices, or general customer support.
- **Configurable**: Fully controlled via `config.yaml` for custom limits, temperatures, and model choices.
- **LLM**: Integrates with OpenAI-compatible endpoints for real-time conversation generation.

## Setup
1. Create a virtual environment and install dependencies:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   playwright install chromium
   ```
2. Make sure PulseAudio is running and configured correctly.

## Usage
Run the main script:
```bash
./venv/bin/python scripts/call.py --number "18003615373" --template general --task "I want to speak with a human agent." --goal "Reach a human agent quickly."
```