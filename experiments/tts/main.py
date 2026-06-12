"""
Whisperdeep TTS experiment — Kokoro voices on sample prose.

Generates one .wav file per (voice, sample) combination under ./output/
so you can listen and compare.

Usage:
    uv run main.py
    uv run main.py --list-voices
    uv run main.py --voice am_adam bm_george --speed 0.85
"""
import argparse
import os
from pathlib import Path

import numpy as np
import soundfile as sf


# ---------------------------------------------------------------------------
# Sample prose drawn from Whisperdeep event types
# ---------------------------------------------------------------------------
SAMPLES = {
    "run_started":    "The dungeon exhales. You descend.",
    "entered_room":   "The floor remembers your weight. Bones, old and pale, are arranged here with a curator's care.",
    "killed_monster": "The Knell-Eyed Verger collapses. Its many eyes close one by one, like candles snuffed by an unseen hand.",
    "low_hp":         "Your blood is loud. The dark presses closer.",
    "found_item":     "Something glints beneath the rot — a blade that has waited longer than memory.",
    "descended":      "Another floor. The light from above is already a rumour.",
    "run_ended":      "Here you fell. The dungeon swallowed your name, and grew a little warmer.",
}

# ---------------------------------------------------------------------------
# Kokoro built-in voices
# af_ = American female, am_ = American male, bf_ = British female, bm_ = British male
# ---------------------------------------------------------------------------
VOICES = {
    "af_heart":   "American female — warm, mid-age",
    "af_bella":   "American female — younger",
    "am_adam":    "American male — neutral",
    "am_michael": "American male — deeper",
    "bf_emma":    "British female — clear, crisp",
    "bm_george":  "British male — authoritative",
    "bm_lewis":   "British male — gravelly",
}


def list_voices() -> None:
    print("\nAvailable voices:\n")
    for name, desc in VOICES.items():
        print(f"  {name:<14}  {desc}")
    print()


def generate(voices: list, speed: float, output_dir: Path) -> None:
    from kokoro import KPipeline

    output_dir.mkdir(parents=True, exist_ok=True)

    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}")
    if device == "cuda":
        print(f"GPU: {torch.cuda.get_device_name(0)}")

    # lang_code "a" = American English; use "b" for British voices
    pipeline_a = KPipeline(lang_code="a", device=device)
    pipeline_b = KPipeline(lang_code="b", device=device)

    for voice in voices:
        lang = "b" if voice.startswith("b") else "a"
        pipeline = pipeline_b if lang == "b" else pipeline_a
        print(f"\n--- Voice: {voice} ({VOICES.get(voice, 'custom')}) ---")

        for event, text in SAMPLES.items():
            print(f"  {event}: {text[:60]}...")
            generator = pipeline(text, voice=voice, speed=speed, split_pattern=None)

            chunks = []
            for _, _, audio in generator:
                chunks.append(audio)

            if not chunks:
                print(f"    [no audio produced]")
                continue

            audio = np.concatenate(chunks)
            filename = output_dir / f"{voice}__{event}.wav"
            sf.write(str(filename), audio, samplerate=24000)
            print(f"    saved: {filename.name}  ({len(audio)/24000:.1f}s)")

    print(f"\nAll files written to: {output_dir.resolve()}")
    print("\nListen and compare — pick your favourite voice for the Whisperer.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Whisperdeep TTS voice comparison")
    parser.add_argument(
        "--voice", nargs="+", default=list(VOICES.keys()),
        help="Voice(s) to generate (default: all)"
    )
    parser.add_argument(
        "--speed", type=float, default=0.9,
        help="Speaking speed multiplier (default: 0.9 — slightly slower for atmosphere)"
    )
    parser.add_argument(
        "--list-voices", action="store_true",
        help="Print available voices and exit"
    )
    parser.add_argument(
        "--output", default="output",
        help="Output directory (default: ./output)"
    )
    args = parser.parse_args()

    if args.list_voices:
        list_voices()
        return

    unknown = [v for v in args.voice if v not in VOICES]
    if unknown:
        print(f"Unknown voices: {unknown}")
        print("Run with --list-voices to see available voices.")
        return

    generate(voices=args.voice, speed=args.speed, output_dir=Path(args.output))


if __name__ == "__main__":
    main()
