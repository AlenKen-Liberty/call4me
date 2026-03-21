# Call4Me

Call4Me is an automated AI phone assistant that connects to Google Voice via headed Chromium and PulseAudio to dial phone numbers, process audio (STT), generate responses (LLM), and playback synthesized voice (TTS).

**🎯 Target Audience:** This project is specially designed for individuals who are not proficient in English or face language barriers. Call4Me acts as your personal AI representative to handle phone calls, navigate complex menus, and communicate on your behalf seamlessly.

## ✨ Technical Features

- **🧠 Auto-Learning Memory System**: Intelligently remembers past calls. It learns and stores IVR maps, strategies, and conversation tips locally in SQLite, making future calls to the same numbers faster and more efficient.
- **📜 Interactive Scripts & Flexible Tasks**: Supports custom tasks and dynamic, interactive scripts. Whether you need to book a flight, dispute a charge, or just ask for prices, the AI adapts its script on the fly based on the conversation.
- **💸 Completely Free (Except LLM)**: The core pipeline utilizes powerful, free local models—Faster-Whisper for Speech-to-Text (STT) and Piper for Text-to-Speech (TTS). The only potential cost is your API usage with OpenAI-compatible LLM endpoints for conversation generation.
- **🤖 Automated Call Navigation**: Easily navigates complicated IVR phone trees by listening, understanding voice prompts, and pressing keys automatically.
- **⚙️ Highly Configurable**: Fully controlled via `config.yaml` to customize limits, response templates, and model choices.

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