# Panda MINI Soundboard

A desktop soundboard for the **WORLDE Panda MINI** MIDI controller. Put any sound (or video) file on
any of the 8 pads and hit them to play into your headphones and, through a virtual cable,
into Discord, OBS or Zoom as if it came from your microphone. The 25 keys play a simple synth.

The window looks like the controller: the buttons, knobs, sliders and pads sit where they are
on the real device, and they light up when you use them.

## Quick start

```bash
pip install -r requirements.txt
python -m app.main
```

1. Plug in the Panda MINI. The pill at the top turns green when the app finds it.
2. The first time, click **Set up controller** and hit **Pad 1 … Pad 8** on the controller in
   order. Then move each slider and turn each knob. (Press **Skip** for any you don't need, or
   **Done** to stop early.) This matches every on-screen control to your real one, whatever
   bank or preset your controller uses.
3. Give each pad a sound. Do one of these:
   - click an empty pad
   - drop a file onto a pad
   - right-click a pad (or use its **⋯** button) and choose **Change sound…**

   Almost any file works: WAV, MP3, OGG, FLAC, M4A/AAC, WMA, OPUS, AIFF, and the audio track
   of MP4/MOV/MKV/WEBM videos. The app keeps its own copy, so you can move or delete the
   original.
4. Hit the pads. Other ways to play them:
   - click them
   - press **1–8** on your computer keyboard

   **Esc** or **Stop all sounds** silences everything.

### Pad options (right-click a pad or use its ⋯ button)

| Option | What it does |
| --- | --- |
| When you hit the pad | Choose one: **Play once** (hitting again restarts), **Play / stop**, **Play while held down**, or **Loop**. |
| Volume | Loudness of this pad only. |
| Play in my headphones / Send to Discord mic | Choose where this pad is heard. |
| Match to a pad on my controller… | Re-learn this one pad. |
| Rename… / Remove sound | Change the name shown on the pad, or clear the pad. |

### Sliders

| Slider | Controls |
| --- | --- |
| 1 | Pads in your headphones |
| 2 | Pads on the Discord mic |
| 3 | Keyboard synth |
| 4 | Master volume |

Right-click any slider or knob to match it to your controller on its own.

## Playing pads into Discord

1. Install the free [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) and restart the app. It
   picks **CABLE Input** as the **Discord mic** output automatically.
2. In Discord go to *User Settings → Voice & Video*. Set **Input Device** to **CABLE Output**.
3. On the same page turn off *Krisp / Noise Suppression* and *Echo Cancellation*. Otherwise
   Discord may cut your sounds.
4. To keep talking with your real microphone too:
   - open Windows *Sound settings → More sound settings → Recording*
   - open your microphone's *Properties → Listen*
   - tick **Listen to this device** and choose **CABLE Input**

The **?** button next to the Discord mic picker shows these steps in the app.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| "Another program is using the controller" | Windows lets only one app open a MIDI device at a time. Close your DAW (FL Studio, Ableton…) and the app reconnects by itself. |
| A pad plays the wrong sound, or a pad does nothing | Click **Set up controller** again. BANK and the Worlde editor can change what the pads send. |
| No sound in Discord | Check that the green meter next to **Discord mic** moves when you hit a pad, then check Discord's input device (see above). |

Settings, imported sounds and logs are kept in `%APPDATA%\PandaMINI` for the packaged app, and in
`user_data/` when running from source. Settings from the previous version are imported
automatically on first start.

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest tests
```

| Folder | Contents |
| --- | --- |
| `app/audio` | Decoding (soundfile → PyAV fallback) and the engine: one PortAudio stream per output, each mixing its own voices. |
| `app/midi` | WinMM (Windows) / mido input, pad matching (MIDI learn) and routing. |
| `app/gui` | The on-screen controller and the main window. |

## License

MIT License
