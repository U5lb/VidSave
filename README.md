<p align="center">
  <img src="backend/assets/avatar.jpg" alt="VidSave Logo" width="200" height="200" style="border-radius: 50%;">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/Aiogram-3.x-red?style=for-the-badge&logo=telegram&logoColor=white" alt="Aiogram">
  <img src="https://img.shields.io/badge/yt--dlp-Supported-green?style=for-the-badge" alt="yt-dlp">
</p>

<h1 align="center">VidSave</h1>

<p align="center">
  <b>Масштабируемый бот для скачивания медиа в Telegram. Архитектура разделена на микросервисы: легкий бэкенд и ресурсоемкие воркеры.</b>
</p>

Воркер можно запустить на любом домашнем ПК, сервере или одноплатнике (например, **Orange Pi** / Raspberry Pi). Главное условие — **резидентский (домашний) IP-адрес**. Если IP принадлежит датацентру, YouTube будет жестко блокировать скачивание. Бэкенду при этом всё равно на IP, поэтому его удобно держать на обычном VPS.

## Особенности проекта

* **Файлы до 2 ГБ**: Локальный сервер Telegram Bot API обходит стандартные лимиты бота и позволяет загружать тяжелые видео.
* **Ram-Диск**: Медиа скачиваются и обрабатываются прямо в оперативной памяти (через `tmpfs` на 2 ГБ). Это спасает накопители от быстрого износа. Минус — требуется от 4 ГБ ОЗУ. Если оперативки мало, загрузку можно перенаправить на обычный диск, тогда хватит и 2 ГБ.
* **Правильное отображение в Telegram**: Принудительная конвертация в H.264 (`avc1`) и парсинг реальных размеров кадра (чтобы видео не сплющивало при просмотре).
* **Масштабирование**: Бэкенд и воркеры общаются по WebSocket. К одному бэкенду можно подключить сколько угодно воркеров для распределения нагрузки.

---

## Установка и запуск

Понадобятся сервер, `git` и `docker` (с плагином `compose`). На VPS также нужно настроить SSL. Если используете Traefik, понадобится домен; с Certbot можно обойтись голым IP.

### 1. Клонирование репозитория (VPS)

Клонируем проект на сервер с бэкендом:
```bash
git clone https://github.com/u5lb/VidSave.git
cd VidSave
```

---

### 2. Настройка Backend (Основной бот на VPS)
Бэкенд отвечает за общение с пользователем, базу данных и раздачу задач.

Создаем и заполняем конфиг:
```bash
nano .env
```

```ini
# Токен бота от @BotFather
BOT_TOKEN=токен_без_кавычек

# Данные для подключения к PostgreSQL
DB_URL="postgresql+asyncpg://tgyt_user:SecretPassword2026@postgres-db:5432/tgyt_database"
WEB_APP_URL="https://example.com" # Заглушка, Web App пока не реализован

# Секретный пароль для защиты WebSocket шлюза от чужих воркеров
WORKER_TOKEN=MySuperSecretToken20261

# Ссылка на стартовую картинку
MAIN_PHOTO_ID="https://raw.githubusercontent.com/u5lb/VidSave/main/backend/assets/avatar.jpg"

# Настройки базы данных
POSTGRES_USER=tgyt_user
POSTGRES_PASSWORD=SecretPassword2026
POSTGRES_DB=tgyt_database
```

Запускаем бэкенд:
```bash
docker compose up -d
```

---

### 3. Настройка Worker (Сервер скачивания)
Воркер делает всю грязную работу: качает через `yt-dlp`, режет через `ffmpeg` и грузит в Telegram.

Клонируем проект уже на домашний сервер/Pi:
```bash
git clone https://github.com/u5lb/VidSave.git
cd VidSave/worker
nano .env
```

```ini
# Строка подключения к бэкенду на VPS (тот самый секретный пароль)
SERVER_URL=wss://поддомен.ваш_домен/ws/worker/worker_pi?token=MySuperSecretToken20261

# Путь до локального контейнера Telegram API
TELEGRAM_API_URL=http://vidsave_telegram-api:8081

# Тот же токен бота
BOT_TOKEN=токен_без_кавычек

# Юзернейм бота без @
BOT_USERNAME=YourBotName

# Данные для локального Telegram API (получать на https://my.telegram.org)
TELEGRAM_API_ID=00000000
TELEGRAM_API_HASH=000000dddaaa0000aaabbb000222ddd000
```

#### Выбор сетевой архитектуры (Важно!)
В папке `worker/` нужно правильно отредактировать конфиг `docker-compose.yml` в зависимости от вашего роутера.

**Вариант А: Роутер с обходом блокировок**
Если на роутере уже настроен обход sTGWS + Zapret, используйте базовый конфиг. Контейнеры просто делят общий RAM-диск.

<details>
<summary>Показать docker-compose.yml для Варианта А</summary>

```yaml
---
services:
  vidsave_worker:
    build: .
    container_name: vidsave_pi_worker
    restart: always
    env_file:
      - .env
    volumes:
      - ramdisk_downloads:/app/downloads

  telegram-api:
    image: aiogram/telegram-bot-api:latest
    container_name: vidsave_telegram-api
    restart: always
    env_file:
      - .env
    environment:
      TELEGRAM_LOCAL: "true"
    volumes:
      - ramdisk_downloads:/app/downloads

volumes:
  ramdisk_downloads:
    driver_opts:
      type: tmpfs
      device: tmpfs
      o: size=2500M,uid=1000,mode=1777
```
</details>

**Вариант Б: Локальный VPN / Zapret / AmneziaWG на хосте**
Если роутер обычный, обход блокировок придется настраивать прямо на сервере, разделяя трафик:
* **YouTube (воркер)**: Пускаем через Zapret, чтобы обойти замедление и сохранить домашний IP (YouTube банит датацентры).
* **Telegram API**: Выносим в изолированную Docker-сеть `vpn_net`, трафик которой заворачиваем в туннель AmneziaWG или Xray.

В этом конфиге для `vpn_net` жестко задан **MTU 1360**, чтобы пакеты не терялись в туннеле. Вам останется только настроить маршрутизацию в самом VPN-клиенте.

<details>
<summary>Показать docker-compose.yml для Варианта Б</summary>

```yaml
---
services:
  vidsave_worker:
    build: .
    container_name: vidsave_pi_worker
    restart: always
    env_file:
      - .env
    volumes:
      - ramdisk_downloads:/app/downloads
    networks:
      - vpn_net

  telegram-api:
    image: aiogram/telegram-bot-api:latest
    container_name: vidsave_telegram-api
    restart: always
    env_file:
      - .env
    environment:
      TELEGRAM_LOCAL: "true"
    volumes:
      - ramdisk_downloads:/app/downloads
    networks:
      - vpn_net

volumes:
  ramdisk_downloads:
    driver_opts:
      type: tmpfs
      device: tmpfs
      o: size=2500M,uid=1000,mode=1777

networks:
  vpn_net:
    driver: bridge
    driver_opts:
      com.docker.network.driver.mtu: 1360
    ipam:
      config:
        - subnet: 10.20.0.0/16
```
</details>

<details>
<summary>Пример маршрутизации для AmneziaWG</summary>

Возьмите свой готовый конфиг от Amnezia и добавьте недостающие строки (`Table`, `PostUp`, `PostDown`), чтобы завернуть подсеть Docker в туннель.

```ini
[Interface]
Address = АЙПИ_В_ВПН_СЕТИ/24
# Закомментировано, чтобы не сломать DNS самого хоста
# DNS = 1.1.1.1, 1.0.0.1
PrivateKey = ВАШ_PRIVATE_KEY

# Отключаем глобальную маршрутизацию (чтобы сервер не ушел в VPN целиком)
Table = off 

# Направляем трафик изолированной сети Docker (10.20.0.0/16) в VPN
PostUp = ip rule add from 10.20.0.0/16 table 120
PostUp = ip route add default dev %i table 120
PostUp = iptables -t nat -A POSTROUTING -s 10.20.0.0/16 -o %i -j MASQUERADE

# Очищаем правила при отключении
PostDown = iptables -t nat -D POSTROUTING -s 10.20.0.0/16 -o %i -j MASQUERADE
PostDown = ip route del default dev %i table 120
PostDown = ip rule del from 10.20.0.0/16 table 120

# ... ваши параметры обфускации (Jc, S1, H1 и т.д.) ...

[Peer]
PublicKey = ВАШ_PUBLIC_KEY
PresharedKey = ВАШ_PRESHARED_KEY
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = IP_СЕРВЕРА:ПОРТ
```
</details>

Запускаем воркер:
```bash
docker compose up -d --build
```

---

## Управление и логирование

Логи загрузок (yt-dlp):
```bash
docker logs vidsave_pi_worker -f
```

Сетевые логи локального Telegram API:
```bash
docker logs vidsave_telegram-api -f
```

Перезапуск воркера после изменений кода:
```bash
docker compose up -d --build
```
