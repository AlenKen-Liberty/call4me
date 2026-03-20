# Telephony Options Comparison for Call4Me AI Phone Agent

**Context:** Oracle Cloud ARM64 (aarch64, 4-core Neoverse-N1, 24GB RAM, no GPU), Python-based, outbound PSTN calls to US customer service numbers, bidirectional real-time audio for local STT/TTS processing.

**Last updated:** 2026-03-20

---

## Option 1: Twilio Media Streams (WebSocket)

### How it works
Twilio originates/receives the PSTN call in their cloud. You provide a TwiML `<Connect><Stream>` instruction that tells Twilio to open a WebSocket to your server. Audio flows bidirectionally over that WebSocket: you receive the caller's audio and send back synthesized audio.

### Setup complexity
- **Effort: LOW** — Easiest to prototype of all options
- Sign up for Twilio, buy a number (~$1.15/mo), write a TwiML webhook + WebSocket server
- ~50 lines of Python (Flask/FastAPI + websockets) to get audio flowing
- No PBX to install, no SIP config, no firewall rules
- Your server only needs an inbound HTTPS endpoint + WebSocket listener
- ARM64 is irrelevant — Twilio handles all telephony; your server just runs Python

### Audio format & quality
- **Fixed at 8kHz mu-law (G.711)** — this is the critical limitation
- Mono, 8-bit mu-law encoded, base64 wrapped in JSON over WebSocket
- Frequency range limited to 300Hz-3.4kHz (narrowband telephony)
- Must convert to 16kHz linear PCM for most STT engines (upsampling introduces artifacts)
- No option for wideband/L16/16kHz — you get what PSTN gives you

### Audio latency
- **~200-400ms transport overhead** (Twilio cloud -> your server WebSocket)
- Twilio's benchmark showed **~950ms average end-to-end** for AI voice agents
- WebSocket adds framing overhead vs raw TCP/UDP
- Geographic distance matters — your Oracle Cloud region to Twilio's media servers
- Base64 encoding/decoding adds CPU overhead (trivial but nonzero)

### Bidirectional streaming
- Fully supported via `<Connect><Stream>` bidirectional mode
- Receive: JSON messages with base64 mu-law audio chunks
- Send: JSON messages with base64 mu-law audio back to Twilio
- Clear mark/media/stop message protocol
- Well-documented, battle-tested

### Call control
- **Excellent** — full REST API for originating calls, hanging up, transferring
- DTMF sending via API (`<Play digits="1234">`)
- Call status webhooks (ringing, answered, completed)
- SIP headers, call recording, conferencing all available
- Python SDK (`twilio` package) is mature and well-maintained

### ARM64 compatibility
- **Perfect** — nothing runs on your server except Python
- All Twilio Python SDK packages are pure Python or have ARM64 wheels

### Python SDK quality
- `pip install twilio` — one of the best telecom Python SDKs
- Extensive examples, including Media Streams + OpenAI Realtime integration
- Active maintenance, good typing support

### Cost
- Phone number: ~$1.15/month
- Outbound calls: **$0.014/min** (US)
- Media Streams: included (no extra charge)
- A 10-min call costs ~$0.14 (vs ~$0.05 with SIP trunk)
- **~2.8x more expensive than SIP trunk options**

### Reliability & scalability
- Enterprise-grade, 99.95% SLA
- Handles thousands of concurrent calls without you managing anything
- Auto-scales — you just pay more

### Community & docs
- **Best-in-class documentation** among all options
- Huge community, Stack Overflow presence, official tutorials
- OpenAI + Twilio integration examples from both companies

---

## Option 2: Asterisk PBX + SIP Trunk (Telnyx/VoIP.ms) via AudioSocket

### How it works
Asterisk runs locally on your ARM64 server. It registers with a SIP trunk provider (Telnyx, VoIP.ms) for PSTN connectivity. When a call is placed, Asterisk's dialplan routes audio to the AudioSocket application, which streams raw PCM audio over a simple TCP socket to your Python app. Your app processes audio (STT) and sends synthesized audio (TTS) back over the same TCP connection.

### Setup complexity
- **Effort: MEDIUM-HIGH**
- Install Asterisk: `sudo apt install asterisk` (ARM64 packages available on Ubuntu)
- Configure pjsip.conf (SIP trunk registration) — ~50-80 lines of config
- Configure extensions.conf (dialplan with AudioSocket) — ~20-30 lines
- Configure SIP trunk provider (Telnyx/VoIP.ms portal)
- Open firewall for SIP (UDP 5060) and RTP (UDP 10000-20000)
- Write Python TCP server for AudioSocket protocol (~100-150 lines)
- AudioSocket protocol is simple: 3-byte header (type + length) + raw PCM payload
- Total config: ~200-300 lines across config files + Python code
- **Known issues:** AudioSocket on Asterisk 20.x has reported inconsistent audio flow; Asterisk 22/23 has fixes but also some regressions with slin16

### Audio format & quality
- **AudioSocket supports 16kHz signed linear PCM (slin16)** — major advantage
- Raw uncompressed audio, no base64 wrapping, no JSON framing
- 16-bit, 16kHz, mono, little-endian — ideal for STT engines
- However: Asterisk 23 has a reported bug where AudioSocket defaults to 8kHz despite slin16 argument
- If using G.722 on the SIP trunk side, Asterisk transcodes to slin16 internally
- Quality depends on SIP trunk codec negotiation (G.711, G.722, Opus)

### Audio latency
- **~20-50ms transport** (local TCP socket on same machine)
- This is the **lowest transport latency** of all options — audio never leaves your server
- AudioSocket is raw TCP, no WebSocket framing, no HTTP overhead
- 20ms audio frames (320 bytes at 16kHz)
- Total pipeline latency dominated by STT/LLM/TTS, not transport

### Bidirectional streaming
- AudioSocket is inherently bidirectional over a single TCP connection
- Read audio frames from socket, write audio frames back
- Simple protocol: type 0x10 = UUID, 0x11 = silence, 0x12 = audio payload
- No complex message parsing — just raw PCM with minimal headers
- **Simpler than WebSocket** for raw audio streaming

### Call control
- Originate calls via AMI (Asterisk Manager Interface) or ARI (Asterisk REST Interface)
- `panoramisk` Python library for AMI, or `ari-py` for ARI
- DTMF: AudioSocket receives DTMF events (type 0x10); sending DTMF requires AMI/ARI
- Hangup detection: socket closes when call ends
- Transfer, conferencing possible but more complex via dialplan/ARI
- **More complex than Twilio's REST API** but fully functional

### ARM64 compatibility
- **Good** — Asterisk has official ARM64 packages in Ubuntu/Debian repos
- `sudo apt install asterisk` works on aarch64
- Docker images available for ARM64 (e.g., `andrius/asterisk`)
- AudioSocket module included in standard builds
- Asterisk 22.x confirmed building on ARM64

### Python SDK quality
- `panoramisk` (AMI client) — functional but not heavily maintained
- `ari-py` (ARI client) — works but documentation is sparse
- AudioSocket has no official Python library — but protocol is simple enough to implement in ~100 lines
- Community Python AudioSocket server exists: `silentindark/audiosocket_server`
- **Less polished than Twilio/Telnyx SDKs**

### Cost
- Asterisk: **free** (open source, runs locally)
- SIP trunk (Telnyx): ~$1/mo number + **~$0.005/min**
- SIP trunk (VoIP.ms): ~$0.85/mo number + **~$0.01/min** (premium) or ~$0.005/min (value)
- A 10-min call costs ~$0.05 — **cheapest option**

### Reliability & scalability
- Asterisk is proven technology (20+ years)
- Single-server, single-process — handles ~50-100 concurrent calls on 4 cores
- AudioSocket has reported stability issues in some versions (high CPU bug #234)
- You manage everything: updates, monitoring, SIP registration health
- **More operational burden** than cloud options

### Community & docs
- Asterisk community is large but aging — most expertise is in traditional PBX use cases
- AudioSocket documentation is minimal (1-2 pages on docs.asterisk.org)
- AI voice agent use of AudioSocket is relatively new — fewer examples
- Active community forum (community.asterisk.org) with responsive developers

---

## Option 3: FreeSWITCH + SIP Trunk via mod_audio_stream

### How it works
FreeSWITCH runs locally, similar to Asterisk. The `mod_audio_stream` module streams audio to a WebSocket endpoint. Your Python WebSocket server receives L16 audio and sends responses back. FreeSWITCH handles SIP trunk registration and PSTN connectivity.

### Setup complexity
- **Effort: HIGH**
- FreeSWITCH must be compiled from source on ARM64 (no pre-built ARM64 .deb packages from SignalWire)
- `mod_audio_stream` is a third-party module (not included in FreeSWITCH core) — must be compiled separately
- **mod_v8 does NOT build on ARM64** — FreeSWITCH's bootstrap.sh explicitly skips it for ARM
- Build dependencies are heavy: libfreeswitch-dev, libssl-dev, zlib1g-dev, libevent-dev, libspeexdsp-dev
- FreeSWITCH XML configuration is notoriously verbose — expect 500+ lines of config
- Dialplan configuration for mod_audio_stream
- Total effort: 1-3 days just to get it compiling and running on ARM64

### Audio format & quality
- mod_audio_stream sends **L16 (16kHz, 16-bit signed linear PCM)** over WebSocket
- Higher quality than Twilio's 8kHz mu-law
- Can negotiate wideband codecs (G.722, Opus) on SIP trunk side
- FreeSWITCH has excellent codec support and transcoding

### Audio latency
- **~30-80ms transport** (local WebSocket)
- Slightly higher than Asterisk AudioSocket (TCP) due to WebSocket framing
- Still very low — audio stays on your server
- FreeSWITCH's multi-threaded architecture handles audio efficiently

### Bidirectional streaming
- mod_audio_stream supports bidirectional WebSocket streaming
- Send audio back as L16 frames via WebSocket
- Works, but less battle-tested than Asterisk AudioSocket for this use case

### Call control
- ESL (Event Socket Library) — powerful programmatic control
- `python-ESL` or `greenswitch` for Python
- Originate calls, send DTMF, transfer, conference — all supported
- FreeSWITCH's ESL is arguably more powerful than Asterisk's AMI/ARI
- Lua/Python scripting available for dialplan logic

### ARM64 compatibility
- **POOR** — this is the dealbreaker
- FreeSWITCH 1.10.12 "added ARM64 support" but in practice:
  - mod_v8 cannot build on ARM64 (libv8 not available)
  - Must compile from source — no official ARM64 packages
  - Build process is fragile on ARM64
  - mod_audio_stream is third-party and must also be compiled
- **Expect significant build pain on ARM64**

### Python SDK quality
- `python-ESL` — works but requires compiling against FreeSWITCH headers
- `greenswitch` — pure Python ESL client, more portable
- mod_audio_stream has no Python SDK — you write a WebSocket server
- Overall: **less convenient than Asterisk for this use case**

### Cost
- FreeSWITCH: **free** (open source)
- Same SIP trunk costs as Asterisk option
- A 10-min call: ~$0.05

### Reliability & scalability
- FreeSWITCH handles thousands of concurrent calls (better than Asterisk at scale)
- Multi-threaded architecture
- But: build/maintenance complexity on ARM64 is a major concern
- mod_audio_stream is a community module — less tested than core modules

### Community & docs
- FreeSWITCH community is smaller than Asterisk's
- Documentation hosted on SignalWire's developer portal
- mod_audio_stream has minimal documentation (GitHub README only)
- ARM64 build issues have open GitHub issues with limited resolution

---

## Option 4: LiveKit + livekit-sip + SIP Trunk (WebRTC-based)

### How it works
LiveKit server runs locally (or in the cloud). The livekit-sip bridge connects SIP trunks to LiveKit rooms. Your Python agent joins the LiveKit room, receives audio via WebRTC, processes it, and sends audio back. The SIP participant in the room is the phone call.

### Setup complexity
- **Effort: MEDIUM**
- LiveKit server: single Go binary or Docker container
- livekit-sip: separate service (Docker container with host networking)
- Redis required (for signaling between services)
- Configure SIP trunk in LiveKit (API calls or YAML)
- Python agent: `pip install livekit-agents` — well-structured framework
- Official example: `livekit-examples/outbound-caller-python`
- **Total: ~3-4 services to run (LiveKit server, SIP bridge, Redis, your agent)**
- Docker Compose simplifies this significantly
- SIP bridge needs host networking + UDP ports 5060, 10000-20000

### Audio format & quality
- WebRTC audio: **Opus codec at 48kHz** — the best audio quality of all options
- LiveKit internally uses Opus, which is wideband/fullband
- When bridging SIP, quality depends on SIP trunk codec (G.711/G.722/Opus)
- The WebRTC leg (your agent <-> LiveKit) is high quality
- Net effect: better than Twilio (8kHz mu-law) but the PSTN leg is still limited by the carrier

### Audio latency
- **LiveKit local: ~50-100ms** (WebRTC optimized for low latency)
- **But SIP bridge adds latency:** users report latency "doubles in telephony contexts"
- GitHub issue #3685: "Latency doubles in telephony contexts" — acknowledged problem
- Telnyx benchmark claims LiveKit has higher latency than their native solution
- WebRTC jitter buffer + SIP bridge processing adds ~100-200ms vs direct SIP
- **Effective latency: ~200-400ms transport**, comparable to Twilio

### Bidirectional streaming
- Excellent — WebRTC is inherently bidirectional
- LiveKit Agents framework handles audio tracks natively
- `agent.on("track_subscribed")` to receive audio
- Publish audio tracks to send back to the room
- Well-abstracted in the Python SDK

### Call control
- Outbound calls: `CreateSIPParticipant` API
- Hangup: disconnect the SIP participant
- DTMF: `SendDTMF` API on the SIP participant
- Transfer: more complex (disconnect and reconnect)
- Call status via room events
- Less mature than Twilio's call control but functional

### ARM64 compatibility
- **MIXED**
- LiveKit server: Go binary, multi-arch Docker images available (including ARM64)
- livekit-sip: Docker image `livekit/sip` — ARM64 support unclear, some tags show amd64 only
- livekit-agents Python SDK: pure Python, works on ARM64
- **Risk: livekit-sip may not have ARM64 Docker images** — may need to build from source (it's Go, so cross-compile is possible)
- Recent GitHub issue about ARM64 Docker image build failures for agents

### Python SDK quality
- `livekit-agents` — **excellent, modern, well-maintained**
- Built-in VoicePipelineAgent for STT -> LLM -> TTS pipeline
- Plugins for many STT/TTS providers
- Type hints, async/await, good documentation
- Most actively developed SDK of all options
- **Best Python developer experience** if you want a framework

### Cost (self-hosted)
- LiveKit server: **free** (open source, self-hosted)
- SIP trunk: same as Asterisk (~$1/mo + $0.005/min)
- A 10-min call: ~$0.05

### Cost (LiveKit Cloud)
- Free tier: 1,000 agent minutes/month, 5,000 connection minutes
- SIP participants: connection minutes not charged
- Beyond free tier: $0.01/min for agent sessions
- Phone numbers: extra via SIP trunk provider

### Reliability & scalability
- LiveKit is designed for scale — horizontal scaling, multi-region
- SIP bridge is relatively new (v0.7.x) — less battle-tested than Asterisk/FreeSWITCH
- Multiple concurrent calls handled naturally (each call = a room)
- WebRTC reliability is excellent
- **SIP bridge stability is the main concern** — newer component

### Community & docs
- LiveKit has excellent, modern documentation
- Active GitHub, Discord community
- Good examples for phone call agents specifically
- Growing rapidly in the AI agent space
- SIP-specific docs are thinner than core LiveKit docs

---

## Option 5: Telnyx Direct (Media Streaming API)

### How it works
Similar to Twilio — Telnyx handles PSTN in their cloud. You use the Call Control API to originate calls and start media streaming. Telnyx opens a WebSocket to your server with bidirectional audio. Your server processes and responds in real-time.

### Setup complexity
- **Effort: LOW** — comparable to Twilio
- Sign up for Telnyx, buy a number, configure a TeXML app or Call Control app
- WebSocket server for bidirectional audio (~50-80 lines Python)
- Call Control API to originate calls and start streaming
- `pip install telnyx` for the Python SDK
- Slightly more API-centric than Twilio (less TwiML magic, more explicit API calls)

### Audio format & quality
- **Supports L16 at 16kHz** — major advantage over Twilio's 8kHz mu-law
- Also supports mu-law 8kHz if you prefer
- Can stream in a different codec than the call itself (Telnyx transcodes)
- **Best audio quality of any cloud option** for STT accuracy
- Uncompressed L16 at 16kHz means no lossy encoding artifacts

### Audio latency
- **Telnyx claims sub-200ms round-trip** for voice AI
- Telnyx benchmarked at significantly lower latency than Twilio (950ms)
- Their infrastructure co-locates GPUs and telephony in global PoPs
- WebSocket transport: ~100-200ms depending on server location
- **Lowest latency among cloud/hosted options**

### Bidirectional streaming
- Full bidirectional support via WebSocket
- `stream_action: "start"` with bidirectional mode
- Receive L16/mu-law audio frames
- Send audio back in the same format
- Clear protocol for media events

### Call control
- Call Control API: originate, answer, hangup, transfer, conference
- DTMF sending via `send_dtmf` command
- Call events via webhooks (call.initiated, call.answered, call.hangup)
- TeXML (TwiML-compatible) also available as alternative
- **Comparable to Twilio in capability**

### ARM64 compatibility
- **Perfect** — cloud service, only Python runs on your server
- `telnyx` Python package is pure Python

### Python SDK quality
- `pip install telnyx` — functional but less polished than Twilio's SDK
- Call Control API is well-documented
- Fewer community examples than Twilio
- Media Streaming specifically has growing but limited Python examples
- Pipecat framework has Telnyx transport support

### Cost
- Phone number: ~$1/mo
- Outbound calls (Voice API): varies by area code, reportedly **$0.005-0.007/min** for many US destinations
- Media Streaming: **$0.0035/min** additional charge
- Total per-minute: ~$0.007-0.010/min
- **However:** Telnyx recently raised prices for some US area codes to $0.07/min outbound — check your specific destinations
- A 10-min call: ~$0.07-0.10 (typical) — **cheaper than Twilio, slightly more than raw SIP trunk**

### Reliability & scalability
- Enterprise-grade infrastructure, own global IP network
- Handles scale without self-hosting concerns
- Less market share than Twilio but growing rapidly
- Used by many AI voice agent companies

### Community & docs
- Good API documentation, improving rapidly
- Fewer community resources than Twilio
- Growing presence in AI voice agent space
- Official integration guides for OpenAI, Deepgram, etc.

---

## Option 6: SignalWire (Cloud Platform by FreeSWITCH Creators)

### How it works
SignalWire is a cloud CPaaS built by the creators of FreeSWITCH. They offer two approaches: (1) Traditional Voice API with SWML (SignalWire Markup Language) for call control, or (2) AI Agent API that bundles STT/LLM/TTS into their platform. For your use case (local STT/TTS), you'd use approach (1) with media streaming.

### Setup complexity
- **Effort: LOW-MEDIUM**
- Sign up, get a number, configure SWML script
- SWML is similar to Twilio's TwiML but more powerful
- AI Agent SDK (`pip install signalwire-agents`) is well-designed
- Can also use FreeSWITCH ESL locally and connect to SignalWire for PSTN
- **Caveat:** Their AI Agent API bundles STT/LLM/TTS — you'd be paying for their processing instead of using your local models, which defeats your architecture

### Audio format & quality
- FreeSWITCH-based, supports wide codec range
- Media forking supports various formats
- If using their AI Agent, audio is processed in their cloud (not what you want)
- For raw audio streaming: documentation is less clear than Telnyx/Twilio

### Audio latency
- Built on FreeSWITCH — inherently low-latency media handling
- AI Agent API: ~$0.16/min includes all processing, latency depends on their infra
- For raw media streaming: comparable to Telnyx

### Bidirectional streaming
- SWML supports media streaming
- Less documented than Twilio/Telnyx for raw bidirectional audio
- AI Agent API handles this internally (but uses their STT/TTS, not yours)
- **If you want to use your own STT/TTS, the raw streaming option is less mature**

### Call control
- SWML: comprehensive call control
- REST API for originate, hangup, transfer
- DTMF support
- Comparable to Twilio/Telnyx

### ARM64 compatibility
- Cloud service — ARM64 irrelevant for the cloud components
- Python SDK works on ARM64
- If self-hosting FreeSWITCH component: same ARM64 issues as Option 3

### Python SDK quality
- `signalwire-agents` SDK — new, well-designed, Python-first
- Open source Agent Builder tool
- But: primarily designed for their AI Agent API (bundled STT/LLM/TTS)
- For raw media streaming with your own models: less SDK support

### Cost
- AI Agent API: **$0.16/min** all-in (includes STT, LLM, TTS) — expensive and redundant since you run local models
- Voice API only: ~$0.01/min for US outbound
- Phone number: ~$1/mo
- **The AI Agent pricing doesn't fit your architecture** (local STT/TTS)
- Using just Voice API: comparable to Telnyx/Twilio

### Reliability & scalability
- Production-grade, built by FreeSWITCH team
- Smaller customer base than Twilio
- Growing in AI agent space

### Community & docs
- Good documentation, modern
- Active development (Agent Builder beta launched 2025)
- Smaller community than Twilio/Telnyx
- Strong FreeSWITCH heritage

---

## Summary Comparison Matrix

| Dimension | Twilio Media Streams | Asterisk AudioSocket | FreeSWITCH mod_audio_stream | LiveKit + SIP | Telnyx Direct | SignalWire |
|-----------|---------------------|---------------------|---------------------------|---------------|---------------|------------|
| **Setup effort** | Very Easy | Medium-Hard | Hard | Medium | Easy | Easy-Medium |
| **Time to prototype** | 2-4 hours | 1-2 days | 2-5 days | 4-8 hours | 2-4 hours | 3-6 hours |
| **Audio sample rate** | 8kHz mu-law | 16kHz L16 (slin16) | 16kHz L16 | 48kHz Opus (WebRTC) | 16kHz L16 | Varies |
| **Transport latency** | 200-400ms | **20-50ms** | 30-80ms | 200-400ms | 100-200ms | 100-200ms |
| **E2E latency (reported)** | ~950ms | ~700-900ms* | ~700-900ms* | ~800-1200ms | **~600-800ms** | ~700-900ms |
| **Bidirectional ease** | Easy (JSON/WS) | Easy (raw TCP) | Medium (WS) | Easy (WebRTC) | Easy (WS) | Medium |
| **Call control** | Excellent | Good | Very Good | Good | Excellent | Good |
| **ARM64 compat** | Perfect | Good | **Poor** | Mixed | Perfect | Perfect |
| **Python SDK** | Excellent | Fair | Fair | Excellent | Good | Good |
| **Cost/10-min call** | $0.14 | **$0.05** | **$0.05** | $0.05 (self) | $0.07-0.10 | $0.10 |
| **Monthly base** | $1.15 | $1.00 | $0 (self) | $0 (self) | $1.00 | $1.00 |
| **Ops burden** | None | Medium | High | Medium | None | None |
| **Concurrent calls** | Unlimited | ~50-100 | ~100-500 | ~50-100 | Unlimited | Unlimited |
| **Production maturity** | Proven | Proven (PBX), newer (AudioSocket) | Proven (PBX), experimental (mod_audio_stream) | New (SIP bridge) | Proven | Growing |
| **STT audio quality** | Worst (8kHz) | Very Good (16kHz) | Very Good (16kHz) | Best (48kHz*) | **Best cloud (16kHz L16)** | Good |

*Asterisk/FreeSWITCH E2E latency estimates assume local STT/TTS processing on same machine.
*LiveKit 48kHz is on the WebRTC leg; the PSTN leg is still limited by carrier codec.

---

## Detailed Recommendations

### Lowest Audio Latency: Asterisk AudioSocket

Asterisk AudioSocket has the lowest transport latency (~20-50ms) because audio never leaves your machine — it flows over a local TCP socket. This gives you the most headroom in your latency budget for STT/LLM/TTS processing. The total pipeline latency is dominated by your AI processing, not the telephony layer.

### Easiest Prototype: Twilio Media Streams or Telnyx Direct

Both cloud options get you a working bidirectional audio stream in 2-4 hours with no infrastructure to manage. **Telnyx wins on audio quality** (16kHz L16 vs Twilio's 8kHz mu-law) while being comparable in ease. Twilio wins on documentation and community resources.

### Best Audio Quality for STT: Telnyx Direct (cloud) or Asterisk AudioSocket (self-hosted)

Both offer 16kHz linear PCM — the sweet spot for STT engines. Twilio's 8kHz mu-law requires upsampling and loses information. LiveKit's 48kHz Opus is technically superior but the PSTN leg constrains quality anyway, and the SIP bridge adds latency.

### Best for Solo Developer on ARM64: **Telnyx Direct** (recommended) or **Asterisk AudioSocket** (advanced)

**Primary recommendation: Telnyx Direct Media Streaming**
- Zero infrastructure to manage
- 16kHz L16 audio (best cloud audio for STT)
- Sub-200ms transport latency
- Cheaper than Twilio ($0.007-0.01/min vs $0.014/min)
- Python WebSocket server is ~50-80 lines
- ARM64 is a non-issue (cloud service)
- Good enough for prototype AND production

**Advanced alternative: Asterisk AudioSocket**
- Lowest possible latency (local TCP)
- Cheapest per-minute ($0.005/min)
- Full control over the audio pipeline
- But: more setup, more ops burden, AudioSocket has some known bugs
- Best if you need to minimize costs at scale or want zero cloud dependency for the telephony layer

### What to Avoid

- **FreeSWITCH on ARM64**: Build pain is not worth it. mod_v8 won't compile, mod_audio_stream is third-party, and the whole experience will be frustrating.
- **SignalWire AI Agent API**: You'd be paying $0.16/min for their bundled STT/LLM/TTS when you already have local models. Only use their Voice API if you specifically want SignalWire's infrastructure.
- **LiveKit SIP for production (today)**: The SIP bridge is still maturing. Latency doubling in telephony contexts is a known issue. Great framework for the future, but adds complexity without clear benefit for a single-server setup.

---

## Recommended Architecture for Call4Me

### Phase 1: Telnyx Direct (fastest to working prototype)
```
Your ARM64 Server
  ├── Python WebSocket server (receives 16kHz L16 audio from Telnyx)
  ├── Silero VAD → Sherpa-ONNX STT → LLM (chat2api) → Piper TTS
  └── Send TTS audio back via WebSocket to Telnyx
      ↕ (WebSocket over internet)
Telnyx Cloud
  └── PSTN call to customer service
```
- Cost: ~$1/mo + $0.01/min
- Setup time: 2-4 hours
- Audio: 16kHz L16, good STT quality
- Latency: ~100-200ms transport + your processing

### Phase 2: Add Asterisk AudioSocket (lower latency, lower cost)
```
Your ARM64 Server
  ├── Asterisk PBX (local) ←→ SIP Trunk (Telnyx/VoIP.ms) ←→ PSTN
  ├── AudioSocket TCP ←→ Python agent
  └── Silero VAD → Sherpa-ONNX STT → LLM → Piper TTS
```
- Cost: ~$1/mo + $0.005/min
- Setup time: 1-2 days
- Audio: 16kHz L16 via local TCP
- Latency: ~20-50ms transport + your processing (lowest possible)

### Phase 3: LiveKit SIP (if scaling beyond single server)
- Only if you need multi-server, multi-region, or >50 concurrent calls
- By then, LiveKit SIP bridge will be more mature

---

## Sources

- [Twilio Media Streams Overview](https://www.twilio.com/docs/voice/media-streams)
- [Twilio Media Streams Python Tutorial](https://www.twilio.com/docs/voice/tutorials/consume-real-time-media-stream-using-websockets-python-and-flask)
- [Twilio Voice Pricing (US)](https://www.twilio.com/en-us/voice/pricing/us)
- [Asterisk AudioSocket Documentation](https://docs.asterisk.org/Configuration/Channel-Drivers/AudioSocket/)
- [Asterisk AudioSocket Python Server (GitHub)](https://github.com/silentindark/audiosocket_server)
- [Asterisk AudioSocket slin16 Issue](https://community.asterisk.org/t/audiosocket-application-defaulting-to-8khz-despite-slin16-argument-in-asterisk-23/111906)
- [Asterisk AI Voice Agent with AudioSocket (GitHub)](https://github.com/hkjarral/Asterisk-AI-Voice-Agent)
- [FreeSWITCH ARM64 mod_v8 Build Issue](https://github.com/signalwire/freeswitch/issues/2621)
- [FreeSWITCH mod_audio_stream (GitHub)](https://github.com/amigniter/mod_audio_stream)
- [LiveKit SIP Documentation](https://docs.livekit.io/sip/)
- [LiveKit Outbound Caller Python Example](https://github.com/livekit-examples/outbound-caller-python)
- [LiveKit Agents Telephony Integration](https://docs.livekit.io/agents/start/telephony/)
- [LiveKit Latency Doubles in Telephony (GitHub Issue)](https://github.com/livekit/agents/issues/3685)
- [LiveKit Self-Hosting SIP Server](https://docs.livekit.io/home/self-hosting/sip-server/)
- [LiveKit Pricing](https://livekit.com/pricing)
- [Telnyx Media Streaming over WebSockets](https://developers.telnyx.com/docs/voice/programmable-voice/media-streaming)
- [Telnyx Bidirectional Streaming](https://telnyx.com/release-notes/bi-directional-streaming-support)
- [Telnyx L16 Codec Support](https://telnyx.com/release-notes/media-streaming-codec-update)
- [Telnyx Voice AI Latency Benchmark](https://telnyx.com/resources/voice-ai-agents-compared-latency)
- [Telnyx Voice API Pricing](https://telnyx.com/pricing/voice-api)
- [Telnyx Price Increase Discussion](https://community.freepbx.org/t/telnyx-new-prices-skyrocket-0-07-in-a-lot-of-area-codes-for-outbound-local-us-calls/71025)
- [Twilio Core Latency in AI Voice Agents](https://www.twilio.com/en-us/blog/developers/best-practices/guide-core-latency-ai-voice-agents)
- [SignalWire AI Agent Pricing](https://signalwire.com/pricing/ai-agent-pricing)
- [SignalWire Agents SDK (GitHub)](https://github.com/signalwire/signalwire-agents)
- [VoIP.ms Pricing](https://voip.ms/pricing)
- [VoIP.ms US Rates](https://voip.ms/index.php/en/rates/united-states)
