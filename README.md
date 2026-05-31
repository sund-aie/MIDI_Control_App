# PandaMINI Control App

A feature-rich desktop application specifically designed to interface with the **WORLDE Panda MINI** MIDI controller. It features a custom dual-stream audio engine that routes audio simultaneously to your headphones (for live monitoring) and a Virtual Audio Cable (to play sounds directly into Discord or streaming software).

## Key Features

- **8 Drum Pads** with built-in sounds (Kick, Snare, Hi-hats, Clap, Tom, Rim, Crash).
- **Custom Sample Loading:** Drag and drop your own `.wav` or `.mp3` files, including files with Unicode characters in their names.
- **Dual-Stream Audio Engine:** Listen to your drum sounds in your headphones while seamlessly piping them to Discord without echo.
- **Auto-Configuring WASAPI/MME:** The engine falls back to standard MME gracefully if WASAPI exclusive mode isn't supported by your device.
- **Save & Load Configs:** Keeps your custom sounds and configurations persistent between sessions.

## Setup

1. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Discord Audio Routing (Optional but recommended):**
   - Download and install **[VB-Audio Virtual Cable](https://vb-audio.com/Cable/)**.
   - Set the application's "Soundboard" output to `CABLE Input (VB-Audio Virtual Cable)`.
   - In Discord's Voice & Video settings, set your Input Device to `CABLE Output (VB-Audio Virtual Cable)`.
   - To also send your microphone audio through Discord, right-click your microphone in Windows Sound Settings -> Properties -> Listen tab -> check "Listen to this device" -> select `CABLE Input`.
   - **Crucial:** Turn off "Krisp Noise Suppression" and "Echo Cancellation" in Discord to prevent Discord from automatically muting your drum pads.

3. **Run the App:**
   ```bash
   python -m app.main
   ```

## Requirements

- Python 3.9+
- `PySide6` (GUI)
- `sounddevice`, `soundfile`, `numpy` (Audio Engine)
- `mido` (MIDI Event Handling)

## License
MIT License