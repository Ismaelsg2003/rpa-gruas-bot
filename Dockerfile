# Imagen del bot y del panel de control.
# La imagen oficial de Playwright ya trae Chromium y sus dependencias del sistema.
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot ./bot
COPY dashboard ./dashboard
COPY scripts ./scripts
ENV PYTHONUNBUFFERED=1
CMD ["sh", "-c", "python -m scripts.seed && python -m bot.main"]
