#!/usr/bin/env python3
"""
Decodes current_display.png via ffmpeg and writes the top 140 rows to the
PhotoZone pixel overlay buffer, holding the image for DURATION seconds.
Called from the 'breaking_news' FPP Script playlist entry.

Channel layout (no overlap):
  PhotoZone:  StartChannel 62031,  192×140 = 80640 ch  (rows 0–139)
  TickerZone: StartChannel 142671, 192×52  = 29952 ch  (rows 140–191)

Pixel data starts at byte offset 12 in FPP-Model-Overlay-Buffer-PhotoZone:
  offset 0-3:  uint32_t width
  offset 4-7:  uint32_t height
  offset 8-11: uint32_t flags  (bit 0 = dirty; triggers flushOverlayBuffer)
  offset 12+:  RGB pixel data (width * height * 3 bytes)

Deploy to: /home/fpp/media/scripts/show_display_image.py (chmod +x)
"""
import struct, subprocess, time, os, sys, json

MODEL        = 'PhotoZone'          # 192×140 — does NOT overlap TickerZone channels
IMAGE        = '/home/fpp/media/images/current_display.png'
BUFFER_PATH  = f'/dev/shm/FPP-Model-Overlay-Buffer-{MODEL}'
WIDTH        = 192
HEIGHT       = 140                  # top 140 rows only; TickerZone owns rows 140-191
DURATION     = 20                   # seconds to display the image
PIXEL_OFFSET = 12                   # byte offset where RGB data begins in overlay buffer
FLAGS_OFFSET = 8                    # byte offset of the flags uint32_t

def fpp_cmd(command, args):
    subprocess.run(
        ['curl', '-s', '-X', 'POST', 'http://localhost/api/command',
         '-H', 'Content-Type: application/json',
         '-d', json.dumps({'command': command, 'args': args})],
        capture_output=True
    )

def fpp_put(path):
    subprocess.run(['curl', '-s', '-X', 'PUT', f'http://localhost{path}'],
                   capture_output=True)

# 0. Wait for the image upload to complete before doing anything.
#    The Docker app uploads current_display.png then immediately starts this
#    playlist; a short delay ensures the file is fully written before ffmpeg reads it.
time.sleep(3)

# 1. Force-create the shared memory overlay buffer WITHOUT enabling PhotoZone yet.
#    The /dev/shm buffer persists between runs and still holds the previous image.
#    We must write the new image into it BEFORE enabling, so the overlay never
#    goes live with stale data.
fpp_put(f'/api/overlays/model/{MODEL}/mmap')
time.sleep(0.25)

# 2. Decode PNG -> raw RGB24, crop to top 140 rows (192×140 = 80640 bytes).
#    The source image is 192×192; we only need the photo zone (top portion).
proc = subprocess.run(
    ['ffmpeg', '-i', IMAGE,
     '-f', 'rawvideo', '-pix_fmt', 'rgb24',
     '-vf', f'crop={WIDTH}:{HEIGHT}:0:0',
     '-vframes', '1', 'pipe:1', '-loglevel', 'quiet'],
    capture_output=True
)
pixel_data = proc.stdout
expected = WIDTH * HEIGHT * 3

if len(pixel_data) != expected:
    print(f'ERROR: ffmpeg produced {len(pixel_data)} bytes (expected {expected})',
          file=sys.stderr)
    sys.exit(1)

# 3. Write new image into the buffer while PhotoZone is still disabled.
#    Then enable PhotoZone — it goes live immediately with the correct data,
#    no flash of the previous image.
try:
    with open(BUFFER_PATH, 'r+b') as f:
        f.seek(PIXEL_OFFSET)
        f.write(pixel_data)
        # Clear dirty flag so FPP doesn't flush stale data on enable
        f.seek(FLAGS_OFFSET)
        f.write(struct.pack('<I', 0))
except Exception as e:
    print(f'Overlay buffer write error: {e}', file=sys.stderr)
    sys.exit(1)

# 4. Enable PhotoZone (buffer already has new image), then set dirty to trigger flush.
#    TickerZone is enabled separately by the Docker app's push_ticker_text() call.
fpp_cmd('Overlay Model State', [MODEL, 'Enabled'])
try:
    with open(BUFFER_PATH, 'r+b') as f:
        f.seek(FLAGS_OFFSET)
        f.write(struct.pack('<I', 0x1))  # set dirty bit → FPP output loop flushes
except Exception as e:
    print(f'Dirty flag set error: {e}', file=sys.stderr)
    sys.exit(1)

# 4. Hold for DURATION seconds.
#    TickerZone text effect runs independently via its own overlay buffer.
time.sleep(DURATION)

# 5. Disable PhotoZone so the normal show resumes cleanly after playlist ends.
fpp_cmd('Overlay Model State', [MODEL, 'Disabled'])
