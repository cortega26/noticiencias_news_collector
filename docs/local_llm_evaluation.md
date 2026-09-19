# Local LLM (Ollama) model evaluation — parked

**Status:** parked (not a priority). **Measured:** 2026-09-19.

Ollama is the *last* fallback in the provider chain (NVIDIA → Gemini → Groq →
OpenRouter → Cloudflare → Ollama; see ADR-0009). With ~2 articles/day it is
rarely reached, so changing the local model has little practical effect.

## Current model and rig

- Model: `qwen3-next:80b-a3b-instruct-q4_K_M` (80B MoE, ~3B active, 50 GB).
- Rig: Intel i5-12600K, 125 GB RAM, no GPU (CPU decode is memory-bandwidth bound).
- Measured on a real editing task (~1700 prompt tokens, Spanish JSON output):
  cold load 66 s, prompt 61 tok/s, generation 10.2 tok/s, 119 s end to end,
  valid JSON.
- Architecture fit: MoE with ~3B active parameters is the right shape for CPU.
  Dense models (e.g. `qwen3.8:27b`, 18 GB) read ~9x more weights per token and
  would run ~2–3 tok/s.

## Candidates to compare later (same class: MoE, ~3B active)

| Model | Size (q4_K_M) | Notes |
| --- | --- | --- |
| `nemotron-3.5-lightning:30b-a3b-q4_K_M` | 25 GB | 30B-A3B, 1M context; same vendor as the primary |
| `laguna-xs-2.1:q4_K_M` | 20 GB | 33B-A3B, built for local use, coding-oriented |

Spanish editorial quality of both is **unknown**; it must be measured.

## Blocker

`ollama pull` of the candidates fails with HTTP 412 ("requires a newer
version"): the installed Ollama is 0.32.6, latest was v0.34.2. Upgrading
touches `/usr/local/bin/ollama` and the systemd service, so it was deferred.

## Plan when revisited

1. Upgrade Ollama and confirm the current model still loads.
2. Run the same Spanish headline+summary+key-points task on each candidate
   (report load time, prompt tok/s, generation tok/s, JSON validity, and a
   manual quality read).
3. Switch `[ollama] model` in `config.toml` only if a candidate is clearly
   faster with equal or better Spanish quality.
