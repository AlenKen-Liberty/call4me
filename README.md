# Call4Me

**Your voice on the phone, when you can't use your own.**

---

## The Story

Yesterday, my 15-year-old daughter Reina asked me a simple question:

> *"Dad, so many people struggle with phone calls in English — new immigrants, people with speech problems, grandma when she needs to call the insurance company. Why can't we just have an AI make the call for them?"*

Today, we sat down together and built it — with the help of Claude Code, we went from idea to a working system in a single day. What started as a father-daughter project became something real: an AI phone assistant that actually calls companies, navigates their phone menus, talks to real humans, and gets things done. For free.

Call4Me is for the people who dread making phone calls. Not because they're lazy, but because the language barrier is real, the anxiety is real, and the phone is sometimes the *only* way to get things done in America.

---

## What It Does

You tell Call4Me what you need — in plain language, in any language — and it:

1. **Understands your goal** through a natural conversation (not a form)
2. **Plans the call** — generates a conversation script, anticipates questions, pre-generates voice responses
3. **Dials the number** through Google Voice (free, no Twilio bills)
4. **Navigates the phone tree** — listens to IVR menus and presses the right keys
5. **Talks to real humans** — introduces itself, answers questions, stays on topic
6. **Learns from every call** — remembers what worked, avoids what didn't
7. **Lets you take over anytime** — you're always in control


## Who Is This For?

- **New immigrants** navigating a system in a language they're still learning
- **People with speech disabilities** who are shut out when phone is the only option
- **Anyone with phone anxiety** — millions of people would rather drive across town than make a 5-minute call
- **Elderly family members** trapped in endless phone trees
- **Caregivers** making calls on behalf of someone who can't

---

## Why Call4Me Is Different

| Feature | Call4Me | Cloud AI phone services |
|---------|---------|------------------------|
| **Cost** | Completely free | $0.05-0.15/min adds up fast |
| **Privacy** | 100% local STT & TTS — your calls never leave your machine | Audio sent to cloud servers |
| **Memory** | Learns from every call — remembers IVR paths, company quirks, what worked | Starts from zero every time |
| **Control** | You review the plan, choose the strategy, intervene mid-call | Black box |
| **Planning** | AI interviews you, generates scripts, pre-caches responses | No preparation |
| **Security** | Only shares what you explicitly authorize — declines everything else | Varies |

### Key Technical Features

- **Auto-Learning Memory** — SQLite + vector embeddings remember past calls. Second call to the same company is faster and smarter.
- **Pre-Call Planning** — A dedicated planner LLM analyzes your request, asks only what's missing, generates a conversation tree, and pre-synthesizes TTS responses before dialing.
- **Speculative Response Caching** — Predicts likely responses and pre-generates audio in the background, cutting latency to near-zero for common exchanges.
- **Interactive User Control** — During the call, type `/say` to override the bot, `/inject` to give it guidance, `/script` to see the plan, or `/stop` to hang up.
- **Number Pronunciation** — Speaks numbers like a human: "ten thirty-one" not "one zero three one". Phone numbers in natural three-three-four grouping.
- **Information Security** — Never shares personal data not explicitly authorized. If asked for information you haven't approved, politely declines.
- **Fully Local Voice Pipeline** — [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) (STT) + [Piper](https://github.com/rhasspy/piper) (TTS) run entirely on your machine. No cloud API costs, no privacy concerns.

---

## Real-World Tested

This isn't a demo. Call4Me has been tested in real phone calls with real companies:

- **Spectrum** — Navigated IVR, got transferred between agents, collected standalone internet pricing (15-minute call with two different reps)
- **Verizon** — Passed through 4-level IVR menu, reached a human, gathered fiber availability and pricing details
- **AT&T** — Handled identity verification questions, discussed service options

The bot handles hold music, agent transfers, being asked to repeat information, and the classic "can you spell that?" — all autonomously.

---

## Quick Start

### Prerequisites

- Linux with PulseAudio (tested on Ubuntu 22.04)
- Python 3.10+
- Google Voice account (free)
- An OpenAI-compatible LLM endpoint (local or remote)

### Installation

```bash
git clone https://github.com/AlenKen-Liberty/call4me.git
cd call4me

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configuration

Copy and edit the config file:

```bash
cp config.yaml.example config.yaml
# Edit config.yaml with your LLM endpoint, Google Voice settings, etc.
```

### Making a Call

**Interactive mode** (recommended — plan the call together with AI):

```bash
./venv/bin/python scripts/call.py --number "18005551234" --interactive
```

The system will:
1. Ask you what you need (in your language)
2. Generate a call strategy
3. Show you the plan and let you adjust it
4. Make the call while you watch and can intervene

**Direct mode** (for quick calls with a clear goal):

```bash
./venv/bin/python scripts/call.py \
  --number "18005551234" \
  --task "Check internet service availability" \
  --goal "Get pricing for standalone internet plans" \
  --context "Address: 123 Main St, Anytown NC 27511"
```

### Mid-Call Commands

While the call is active, you can type:

| Command | What it does |
|---------|-------------|
| `/say Hello, can you repeat that?` | Override the bot — your words are spoken next |
| `/inject Ask about senior discounts` | Whisper guidance to the bot without speaking |
| `/script` | Show the current conversation script |
| `/stop` | Hang up immediately |

---

## Architecture

```
You (any language)
  |
  v
[Interviewer] ─── understands your goal, asks only what's missing
  |
  v
[Script Generator] ─── builds conversation tree + decision points
  |
  v
[Speculative Cache] ─── pre-generates TTS for likely responses
  |
  v
[Google Voice + PulseAudio] ─── dials the number
  |
  v
[Call Loop]
  ├── Faster-Whisper (STT) ─── hears what they say
  ├── LLM ─── decides what to say (or uses cached response)
  ├── Piper (TTS) ─── speaks the response
  └── Memory ─── learns for next time
  |
  v
[Post-Call] ─── extracts tips, IVR maps, strategies → SQLite
```

All components run locally. No data leaves your machine.

---

## How It Learns

After every call, Call4Me automatically extracts:
- **IVR navigation paths** — "Press 2, then 1, then 0 to reach a human"
- **Conversation strategies** — "They always ask for the address first"
- **Company quirks** — "Spectrum transfers you if you ask about standalone pricing"

This knowledge is stored locally in SQLite with vector embeddings. The next time you call the same company, the bot already knows the fastest path to a human and what questions to expect.

---

## Built With

- [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) — Local speech-to-text
- [Piper](https://github.com/rhasspy/piper) — Local text-to-speech
- [Google Voice](https://voice.google.com) — Free phone calls
- [PulseAudio](https://www.freedesktop.org/wiki/Software/PulseAudio/) — Audio routing
- [Claude Code](https://claude.ai/claude-code) — AI-assisted development

---

## Contributing

Call4Me is open source and we welcome contributions. Whether you're adding support for new languages, improving the conversation engine, or just fixing a typo — every bit helps someone make a phone call they couldn't make before.

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

<p align="center">
  <i>
    Born from a 16-year-old's birthday wish to help people who struggle on the phone.<br>
    Built in a day with Claude Code. Shared with everyone who needs it.
  </i>
</p>
