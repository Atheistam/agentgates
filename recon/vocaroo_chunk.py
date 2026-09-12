#!/usr/bin/env python3
"""Chase the 500: the chunk route exists (it 404s at /upload and 500s at
/upload/<id>/chunk/0). Test the contract exactly as the bundle builds it —
one file part named 'chunk', nothing else — and print the server's own words.
"""
import secrets
import subprocess
import struct
import math
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")

B62 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
UA = "agentgates-probe/1.0 (+https://agentgates.surge.sh; one upload, no account)"

# a real, listenable wav: 1s 440Hz tone at 8kHz mono
def wav(path, secs=1.0, rate=8000, freq=440):
    n = int(secs * rate)
    data = b"".join(struct.pack("<h", int(12000 * math.sin(2 * math.pi * freq * i / rate)))
                    for i in range(n))
    hdr = (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " +
           struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) +
           b"data" + struct.pack("<I", len(data)))
    open(path, "wb").write(hdr + data)
    return len(hdr + data)


n = wav("recon/tone.wav")
print("wav bytes:", n)

up = "https://upload1.vocaroo.com/apps/main-api/upload"
print("HEAD /alive:", subprocess.run(
    ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-I", "-m", "20", "-A", UA, up + "/alive"],
    capture_output=True, text=True).stdout)

uid = "".join(secrets.choice(B62) for _ in range(22))
cap = "%s/%s" % (up, uid)
print("upload id:", uid, "(len %d)" % len(uid))

r = subprocess.run(["curl", "-s", "-m", "45", "-A", UA,
                    "-H", "Origin: https://vocaroo.com", "-H", "Referer: https://vocaroo.com/",
                    "-F", "chunk=@recon/tone.wav;filename=chunk;type=audio/wav",
                    "-w", "\n[http %{http_code}]", cap + "/chunk/0"],
                   capture_output=True, text=True)
print("chunk/0:", r.stdout.strip()[:400])
if "[http 200]" in r.stdout:
    f = subprocess.run(["curl", "-s", "-m", "30", "-A", UA, "-X", "POST",
                        "-H", "Origin: https://vocaroo.com", "-H", "Referer: https://vocaroo.com/",
                        "-w", "\n[http %{http_code}]", cap + "/finalize"],
                       capture_output=True, text=True)
    print("finalize:", f.stdout.strip()[:400])
print("attempts recorded in recon/vocaroo_attempt.txt")
open("recon/vocaroo_attempt.txt", "a").write("%s %s\n" % (uid, r.stdout.strip()[:200]))
