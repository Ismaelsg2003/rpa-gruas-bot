# Grabar el vídeo de la demo

1. Arranca la demo con más servicios para que haya movimiento:
   `PORTAL_NEW_SERVICE_EVERY=3 python run_demo.py --reset --no-browser` (en PowerShell: `$env:PORTAL_NEW_SERVICE_EVERY=3; python run_demo.py --reset --no-browser`).
2. Espera unos 30 s y, en otra terminal: `cd tools/demo-video` y `python -m http.server 8002`.
3. En una tercera terminal: `python tools/demo-video/record.py docs/video-raw`.
4. Convierte el `.webm` más grande de `docs/video-raw`:

```bash
ffmpeg -ss 2.6 -i docs/video-raw/<video>.webm -c:v libx264 -preset veryfast -crf 24 -pix_fmt yuv420p -movflags +faststart -an docs/demo.mp4
ffmpeg -ss 11.5 -t 22 -i docs/video-raw/<video>.webm -vf "fps=8,scale=1200:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle" docs/demo.gif
```
