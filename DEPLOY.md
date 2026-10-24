# Despliegue en un servidor (Oracle Cloud Always Free)

Guía para publicar la demo en un servidor Linux gratuito, con HTTPS y dos direcciones públicas: una para el panel y otra para la plataforma.

## 1. Crear el servidor

En la consola de Oracle Cloud: **Compute → Instances → Create instance**.

- **Image:** Canonical Ubuntu 24.04 (aarch64).
- **Shape:** Ampere → `VM.Standard.A1.Flex` con **2 OCPU y 12 GB** de memoria. Es el máximo Always Free; comprueba que aparece la etiqueta *Always Free-eligible*.
- **Networking:** crea una VCN nueva con subred pública y **asigna IP pública**.
- **SSH keys:** sube tu llave pública (`oracle_portfolio.pub`).
- **Boot volume:** el valor por defecto (unos 50 GB) entra en el Always Free.

Si sale *Out of host capacity*, prueba otro dominio de disponibilidad o vuelve a intentarlo más tarde.

## 2. Abrir los puertos 80 y 443

En la consola: **Networking → Virtual cloud networks → tu VCN → Security Lists → Default Security List → Add Ingress Rules**:

| Source CIDR | Protocolo | Puerto destino |
|---|---|---|
| 0.0.0.0/0 | TCP | 80 |
| 0.0.0.0/0 | TCP | 443 |

Las imágenes Ubuntu de Oracle traen además un cortafuegos propio (iptables). Dentro del servidor:

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

## 3. Instalar Docker

```bash
ssh -i ~/.ssh/oracle_portfolio ubuntu@IP_DEL_SERVIDOR
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu   # sal y vuelve a entrar para que surta efecto
```

## 4. Desplegar

```bash
git clone https://github.com/Ismaelsg2003/rpa-gruas-bot.git
cd rpa-gruas-bot
cp .env.example .env
nano .env
```

En `.env` cambia:

```ini
PORTAL_SESSION_SECRET=<un valor largo y aleatorio: openssl rand -hex 32>
DEMO_PUBLIC=true
DEMO_RESET_MINUTES=60
# sslip.io convierte la IP en un nombre de dominio gratuito (IP 203.0.113.10 → 203-0-113-10)
PANEL_HOST=panel.203-0-113-10.sslip.io
PLATFORM_HOST=plataforma.203-0-113-10.sslip.io
```

Arranca todo:

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml logs -f bot   # Ctrl+C para salir de los logs
```

Caddy pide los certificados HTTPS automáticamente la primera vez. En uno o dos minutos estarán disponibles:

- `https://PANEL_HOST`: panel de control
- `https://PLATFORM_HOST`: plataforma (usuario `demo`, contraseña `demo1234`)

## 5. Mantenimiento

```bash
git pull && docker compose -f docker-compose.prod.yml up -d --build   # actualizar
docker compose -f docker-compose.prod.yml ps                          # estado
docker compose -f docker-compose.prod.yml restart bot                 # reiniciar el bot
```

Todos los servicios usan `restart: unless-stopped`: si el servidor se reinicia, la demo vuelve a arrancar sola.

## Modo demo pública

Con `DEMO_PUBLIC=true`:

- El bot restablece flota, reglas e historial cada `DEMO_RESET_MINUTES`, porque todos los visitantes comparten el mismo panel.
- La pantalla de login de la plataforma muestra las credenciales de la demo.
- El panel avisa de que es una demo compartida, enlaza a la plataforma y limita el número de reglas.
