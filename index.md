---
layout: default
title: "Hear Me Out"
description: "Interactive evaluation and bias discovery platform for speech-to-speech conversational AI"
---

<div align="center">
  <h1>{{ page.title }}</h1>
  <p style="color: #666; margin: 0.5rem 0;">Interactive evaluation and bias discovery platform for speech-to-speech conversational AI</p>
  
  <!-- Authors -->
  <p style="color: #555; font-size: 1.1rem; margin: 1rem 0;">
    <strong>Shree Harsha Bokkahalli Satish, Gustav Eje Henter, Éva Székely</strong>
  </p>

  <!-- Study-platform contributors: our two names. Order alternates on every visit
       (neither of us is consistently first); filled by the script in _includes/footer.html,
       which sets this line and the footer to the same order. -->
  <p style="color: #555; font-size: 1rem; margin: 0.25rem 0 0.75rem;">
    <span id="contrib-names" style="opacity:0; transition:opacity 0.6s ease;">&nbsp;</span>
  </p>

  <!-- Affiliation with KTH Logo -->
  <div style="display: flex; align-items: center; justify-content: center; gap: 1rem; margin: 1rem 0;">
    <img src="{{ '/assets/KTH_Logo.jpg' | relative_url }}" alt="KTH Royal Institute of Technology" style="height: 40px; width: auto;">
    <p style="color: #666; margin: 0; font-style: italic;">KTH Royal Institute of Technology, Stockholm, Sweden</p>
  </div>

  <p><strong><a href="https://testing-moshi--hearmeout-web-dev.modal.run/" target="_blank">🎙️ Click here to try Hear Me Out Live (Under construction for now! Reach out for a preview!)</a></strong></p>
</div>

**Hear Me Out** is an interactive evaluation and bias discovery platform for speech-to-speech conversational AI. Speech-to-speech models process spoken language directly from audio, without first converting it to text. They promise more natural, expressive, and emotionally aware interactions by retaining prosody, intonation, and other vocal cues throughout the conversation.

---

<div align="center">
  <img src="https://github.com/user-attachments/assets/b282ad4a-354f-4452-ada2-59fafae65629" alt="Hear Me Out Block Diagram" style="max-width: 65%; height: auto;">
</div>

---

## 🏗️ **Architecture**

The backend is three services, set up and run entirely from this repo, behind self-signed SSL (browser mic capture requires HTTPS) and launched by `infra/run_all.sh`:

| Service | Port | Device | Role |
|---|---|---|---|
| **PersonaPlex** | 8000 | GPU | Audio-native speech↔speech LM (NVIDIA `personaplex` moshi fork) — ingests audio via the Mimi codec and responds in token space, no separate ASR. |
| **app-api** | 5001 | GPU | FastAPI app — serves the built frontend + REST: transcription (faster-whisper), offline voice conversion (Seed-VC), and metrics comparison. |
| **MeanVC** *or* **X-VC** | 5002 | CPU / GPU | Real-time streaming voice conversion + the chat-proxy that converts mic audio and forwards it to PersonaPlex. Engine chosen at launch via `VC_ENGINE` (MeanVC = CPU, X-VC = GPU). |

Each backend is an independent **uv** project under `services/<name>/` with its own venv, so X-VC's torch 2.5 / py3.10 never clashes with the others' torch 2.4.

## ⚙️ **Setup**

`infra/setup.sh` is self-bootstrapping and interactive: it installs **uv**, clones the repo (with the `seed-vc` submodule) + MeanVC, `uv sync`s each service into its own venv, downloads all models, generates SSL, and wires up the workspace.

```bash
export HF_TOKEN=hf_xxxxx   # access to gated nvidia/personaplex-7b-v1
curl -fsSL https://raw.githubusercontent.com/shreeharsha-bs/Hear-Me-Out/main/infra/setup.sh -o setup.sh
bash setup.sh              # prompts for workspace, repo, token, etc.
```

- **Workspace** defaults to the current directory — `cd` into your target folder first, or set `WORKSPACE=/path`.
- **Non-interactive** (CI): pass `-y` with preset env, e.g. `HF_TOKEN=… WORKSPACE=/workspace bash setup.sh -y`.
- **X-VC engine** (optional, GPU): pass `--xvc` to also install it into its own venv; select it at run time with `VC_ENGINE=xvc`.

## ▶️ **Running**

```bash
cd <workspace> && bash Hear-Me-Out/infra/run_all.sh
# PersonaPlex :8000   app-api :5001   MeanVC :5002   (all SSL)
```

Set `VC_ENGINE=meanvc|xvc` to pick the voice-conversion engine on `:5002`. `run_all.sh` always serves the Vite build (`frontend/dist`, auto-built if missing).

## 🚀 **Deploying a change**

Edit locally, commit, push — then on the server:

```bash
cd <workspace>/Hear-Me-Out && git pull
bash infra/build-frontend.sh                 # only if the frontend changed
( cd services/<name> && uv sync )            # only if that service's deps changed
# re-run run_all.sh, or restart the affected service
```

---

## **Features**

**Hear Me Out** enables users to experience interactions with conversational models in ways that aren't typically accessible with regular benchmarking systems. Key features include:

- **🎤 Speech-to-Speech Models**: Users can choose from a variety of models that retain vocal cues like prosody and intonation.
- **🔄 Real-Time Voice Conversion**: Step into someone else's voice – literally – and investigate how conversational AI systems interpret and respond to various speaker identities and expressions.
- **⚖️ Side-by-Side Comparisons**: Ask a question with your own voice, then re-ask using a transformed voice. Compare the AI's responses to observe differences in tone, phrasing, or behavior.
- **📊 Insights Through Data**: Visualize metrics like speech rate, sentiment analysis, and more.

<div align="center">
  <img src="https://github.com/user-attachments/assets/42c5cd60-0fe1-4e58-b198-ff12698e3b3a" alt="Hear Me Out Interface Screenshot" style="max-width: 65%; height: auto;">
</div>

Through this immersive experience, we hope users will gain insights into identity, voice, and AI behavior. Ultimately, we aim to surface meaningful questions and inspire future research that promotes fairness and inclusivity with **Hear Me Out**.

---

## 🧪 **Study platform**

Beyond the interactive demo, the same backend runs a **participant-study platform** for controlled voice-conditioning experiments. Set `APP_MODE=study` and `:5001` serves the study app (participant experiment + a token-gated admin dashboard) instead of the Chat/Convert/Metrics UI.

```bash
APP_MODE=study bash infra/build-frontend.sh
APP_MODE=study bash infra/run_all.sh
```

- **Admin** manages studies: scenarios with **timed voice schedules** (natural ↔ converted), target voices, and questionnaires; generates participants with **counterbalanced, gender-conditional** condition assignment; runs analysis and export.
- **Participant flow** (resumable, 1 hour): eligibility → consent → audio check → background → a practice scenario → counterbalanced analytical scenarios → questionnaires → converted-voice playback. The system prompt and voice schedule never reach the browser — the VC engine resolves them server-side.
- **Voice conditions:** stable-natural, stable-converted, VC-activation (natural → converted mid-call), and VC-deactivation (converted → natural).
- **Analysis** yields per-session technical-validity checks, a millisecond diarization timeline (overlaps, barge-ins), speech metrics, and objective VC-quality (WER, speaker similarity, UTMOS), all bundled by an export endpoint.

---

## **Demo Video**

In the demo video, we explore the **Moshi** speech-to-speech model and its responses:

<div align="center">
  <video controls width="100%" style="max-width: 640px;">
    <source src="{{ '/assets/IS_st_KTH_Hear-Me-Out-4th_draft.mp4' | relative_url }}" type="video/mp4">
    Your browser does not support the video tag.
  </video>
</div>

### Example 1: Emotional Awareness

Notice how the model disambiguates between inputs with levity and frustration, correctly reflecting the speaker's emotional state in its responses. This distinction adds a more human-like quality to the interaction.

### Example 2: Voice Conversion - Gender Bias requesting unauthorized access

By applying voice transformations, we simulate how the model might respond to different speaker characteristics. While the differences in these responses are more subtle and inconsistent under repetition, hearing oneself in another voice opens up new perspectives.


### Example 3: Voice Conversion - Gender Bias at Work

<div align="center">
  <video controls width="100%" style="max-width: 640px;">
    <source src="{{ '/assets/Demo_June9th.mp4' | relative_url }}" type="video/mp4">
    Your browser does not support the video tag.
  </video>
</div>


<div class="bottom-section">
  <div style="max-width: 1400px; margin: 0 auto; padding: 0 2rem;">
    
    <h2>📄 License</h2>
    <p>This project is licensed under the terms specified in the <a href="LICENSE">LICENSE</a> file.</p>

    <h2>🤝 Collaborations</h2>
    <p>We welcome contributions and collaboration. If you're in HCI, please reach out.</p>
    
    <hr style="border: none; height: 1px; background: rgba(255,255,255,0.3); margin: 2rem auto; max-width: 400px;">
    
    <p style="font-size: 1.2rem; font-style: italic; margin-bottom: 1rem;">
      <em>Explore Empathy and Conversational AI with Hear Me Out</em>
    </p>
    <p><strong><a href="https://testing-moshi--hearmeout-web-dev.modal.run/" target="_blank" style="background: rgba(255,255,255,0.2); padding: 12px 24px; border-radius: 25px; text-decoration: none !important; display: inline-block; margin-top: 1rem;">🎙️ Try it now</a></strong></p>
    
  </div>
</div>

