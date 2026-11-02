"""Generate the default alarm sound: a harsh, repeating beep-beep-beep.

Uses only the standard library and writes a WAV file. The committed
sounds/alarm.mp3 was made from this with:

    python3 scripts/make_alarm.py /tmp/alarm.wav
    ffmpeg -i /tmp/alarm.wav -codec:a libmp3lame -b:a 128k sounds/alarm.mp3

The Nest plays WAV too, so the ffmpeg step is optional.
"""

import math
import struct
import sys
import wave

RATE = 22050
SECONDS = 10


def tone(freq, length, volume=0.8):
    """A square-ish wave (odd harmonics) with short fades to avoid clicks."""
    n = int(RATE * length)
    fade = int(RATE * 0.005)
    for i in range(n):
        t = i / RATE
        s = sum(math.sin(2 * math.pi * freq * h * t) / h for h in (1, 3, 5, 7))
        env = min(1.0, i / fade, (n - i) / fade)
        yield volume * env * s * 0.8


def silence(length):
    return (0.0 for _ in range(int(RATE * length)))


def pattern():
    """Three fast beeps, a short gap, repeated; pitch alternates each burst."""
    elapsed, burst = 0.0, 0
    while elapsed < SECONDS:
        freq = 2000 if burst % 2 == 0 else 2500
        for _ in range(3):
            yield from tone(freq, 0.09)
            yield from silence(0.05)
        yield from silence(0.25)
        elapsed += 3 * 0.14 + 0.25
        burst += 1


def main(path):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(
            b"".join(struct.pack("<h", int(max(-1, min(1, s)) * 32767)) for s in pattern())
        )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "alarm.wav")
