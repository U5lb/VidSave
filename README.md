<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/Aiogram-3.x-red?style=for-the-badge&logo=telegram&logoColor=white" alt="Aiogram">
  <img src="https://img.shields.io/badge/yt--dlp-Supported-green?style=for-the-badge" alt="yt-dlp">
</p>

<h1 align="center">VidSave</h1>

<p align="center">
  <b>Масштабируемый Telegram-бот для скачивания медиа в telegram. Разделен на микросервисы: легкий бекенд и тяжелые воркеры для загрузки файлов.</b>
</p>

Воркер можно развернуть на любом домашнем ПК, домашнем сервере или одноплатнике (например, **Orange Pi** / Raspberry Pi) главное условие - Резиденсткий айпи у воркера, если айпи у воркера из датацентра - скачивания ваших видео с вашего ютуб канала ниже 20%, Бэкенд не требовальный к айпи и размещен на VPS. 

## Особенности проекта

* **Выгрузка файлов до 2 ГБ**: Использование локального сервера Telegram Bot API позволяет загружать и отправлять файлы размером до **2 ГБ**.
* **Бережем SSD и SD-карты**: Видео скачиваются и обрабатываются исключительно в оперативной памяти (через `tmpfs` RAM-диск на 2 ГБ). Это критически важно для одноплатников, чтобы спасти накопитель от быстрого износа при постоянной перезаписи тяжелых файлов. но это накладывает ограничение по выбору железа - рекомендуемый минимум 4 ГБ оперативной памяти. или перенос загрузки видео в обычную деррикторию на SD/SSD, что снижает требование к оперативной памяти до **2 ГБ**.
* **Гарантированная совместимость**: Принудительная конвертация видео в кодек H.264 (`avc1`) и извлечение реальных размеров кадра для корректного отображения видео с правильным соотношением сторон.
* **Событийная архитектура**: Бекенд и воркеры общаются по WebSocket. Вы можете запустить один бекенд и подключить к нему сколько угодно серверов-воркеров для балансировки нагрузки.

---

## Установка и запуск

Для работы потребуется сервер с установленными `git` и `docker` (с плагином `docker compose`).
вам потребуется на VPS получить ssl через traefik или certbot. для выбора с traefik потребуется домен. с certbot можно поробовать обойтись без домена. 

### 1. Клонирование репозитория

Склонируйте проект на ваш сервер и перейдите в его директорию:
```bash
git clone https://github.com/u5lb/VidSave.git
cd VidSave
```

---

### 2. Настройка Backend (Основной бот)
Бекенд отвечает за общение с пользователем, базу данных и распределение задач.

Перейдите в папку бекенда и создайте конфигурационный файл:
```bash
cd backend
nano .env
```

Заполните минимальные данные в `.env`:
```ini
BOT_TOKEN=ваш_бот_токен_без_ковычек
DB_URL=postgresql+asyncpg://tgyt_user:SecretPassword2026@postgres-db:5432/tgyt_database #если изменили в docker-compose необходимо отредактировать
WEB_APP_URL="https://example.com" #В этой версии проекта не реализован Web App.
WORKER_TOKEN="MySuperSecret123"
MAIN_PHOTO_ID= # Оставьте пустым для первого запуска, после отправьте любое подходящее фото в бота и скопируйте получившийся хеш, вставьте в это поле.
```

Запустите бекенд:
```bash
docker compose up -d
```

---

### 3. Настройка Worker (Сервер скачивания)
Воркер выполняет всю ресурсоемкую работу: скачивание через `yt-dlp`, нарезку через `ffmpeg` и выгрузку в Telegram.

Перейдите в папку воркера и создайте конфиг:
```bash
cd ../worker
nano .env
```

Заполните `.env` воркера:
```ini
BOT_TOKEN=ваш_бот_токен_без_ковычек_как_и_в_первом_.env
SERVER_URL=wss://ДОМЕН_ВАШЕГО_БЕКЕНДА:8000/ws/worker/worker_1?token=ваша_секретная_строка_для_подключения_воркеров

# Данные для запуска локального сервера Telegram API
# Получите их на сайте [https://my.telegram.org](https://my.telegram.org)
TELEGRAM_API_ID=1234567
TELEGRAM_API_HASH=abcdef1234567890abcdef
```

#### Выбор сетевой архитектуры (Важно!)
В папке `worker/` вам нужно выбрать правильную конфигурацию сети в `docker-compose.yml` в зависимости от вашего роутера и провайдера.

**Вариант А: Роутер с обходом блокировок**
Если на вашем роутере уже настроен обход блокировок на уровне всей сети (или вы запускаете воркер на зарубежном сервере с РЕЗИДЕНСКИМ айпи. запустить воркера на VPS не имеет смысла из за жосткой политики youtube против скачивания своих видео), используйте стандартный конфиг. В нём контейнеры просто делят общий RAM-диск.

<details>
<summary>Показать docker-compose.yml для Варианта А</summary>

```yaml
---
services:
  vidsave-worker:
    build: .
    container_name: pi_worker
    restart: always
    env_file:
      - .env
    volumes:
      - ramdisk_downloads:/app/downloads

  telegram-api:
    image: aiogram/telegram-bot-api:latest
    container_name: telegram-api
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
Если ваш роутер обычный, и вы поднимаете туннель (например, AmneziaWG) прямо на хост-машине (вашем ПК или Orange Pi), стандартная сеть Docker могут  конфликтовать с MTU туннеля 
Для этого сценария используйте конфиг с выделенной подсетью и **MTU 1360**:

<details>
<summary>Показать docker-compose.yml для Варианта Б</summary>

```yaml
---
services:
  vidsave-worker:
    build: .
    container_name: pi_worker
    restart: always
    env_file:
      - .env
    volumes:
      - ramdisk_downloads:/app/downloads
    networks:
      - vpn_net

  telegram-api:
    image: aiogram/telegram-bot-api:latest
    container_name: telegram-api
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

Отредактировав `docker-compose.yml` под ваши нужды, запустите воркер:
```bash
docker compose up -d --build
```

---

## Управление и логирование

Посмотреть логи процесса скачивания (yt-dlp):
```bash
cd VidSave/worker
docker logs pi_worker -f
```

Посмотреть сетевые логи локального сервера Telegram API:
```bash
docker logs telegram-api -f
```

Перезапустить воркер после внесения изменений в код:
```bash
docker compose up -d --build
```
