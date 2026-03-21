# Call4Me

Call4Me is an automated AI phone assistant that connects to Google Voice via headed Chromium and PulseAudio to dial phone numbers, process audio (STT), generate responses (LLM), and playback synthesized voice (TTS).

**🎯 Target Audience:** This project is specially designed for individuals who are not proficient in English or face language barriers. Call4Me acts as your personal AI representative to handle phone calls, navigate complex menus, and communicate on your behalf seamlessly.

## ✨ Technical Features

- **🧠 Auto-Learning Memory System**: Intelligently remembers past calls. It learns and stores IVR maps, strategies, and conversation tips locally in SQLite, making future calls to the same numbers faster and more efficient.
- **🗣️ Natural Language Pre-call Planning**: A dedicated `planner_llm` takes a simple natural-language description of your goal, intelligently identifies what's missing, and generates high-quality call scripts without rigid setups.
- **📜 Interactive Scripts & Flexible Tasks**: Supports custom tasks and dynamic, interactive scripts. The system generates plans beforehand and adapts its script on the fly based on the real-time conversation.
- **💸 Completely Free (Except LLM)**: The core pipeline utilizes powerful, free local models—Faster-Whisper for Speech-to-Text (STT) and Piper for Text-to-Speech (TTS). The only potential cost is your API usage with OpenAI-compatible endpoints.
- **🤖 Automated Call Navigation**: Easily navigates complicated IVR phone trees by listening, understanding voice prompts, and pressing keys automatically.
- **⚙️ Highly Configurable & Quiet Interactive Mode**: Fully controlled via `config.yaml` to customize models (separate models for planning vs. real-time calling), and includes a quiet interactive mode for a cleaner terminal experience.

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