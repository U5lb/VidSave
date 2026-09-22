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

Для работы потребуется сервер с установленными `git` и `docker` и `docker compose`).
вам потребуется на VPS получить ssl через traefik или certbot. для выбора с traefik потребуется домен. с certbot можно поробовать обойтись без домена. 

### 1. Клонирование репозитория

Склонируйте проект на Ваш сервер и перейдите в его директорию:
```bash
git clone https://github.com/u5lb/VidSave.git
cd VidSave
```

---

### 2. Настройка Backend (Основной бот)
Бекенд отвечает за общение с пользователем, базу данных и распределение задач.

Первым делом нужно наполнить .env файл
```bash
nano .env
```

Заполните минимальные данные в `.env`:
```ini
# Токен Вашего бота от @BotFather
BOT_TOKEN=токен_без_кавычек

# Строка подключения к PostgreSQL
DB_URL="postgresql+asyncpg://tgyt_user:SecretPassword2026@postgres-db:5432/tgyt_database"#Если что-то меняли в данных подключения к бд незабудьте обновить и здесь.
WEB_APP_URL="https://example.com" # В этой сервии сервиса не реализован web mini app
# Секретный пароль он защищает WebSocket шлюз от чужих воркеров.
WORKER_TOKEN=MySuperSecretToken20261

#ID стартовой картинки
MAIN_PHOTO_ID= #оставьте пустым для первого запуска

#Секреты Postgress
POSTGRES_PASSWORD=SecretPassword2026
POSTGRES_USER=tgyt_user
POSTGRES_DB=tgyt_database

```

Запустите бекенд:
```bash
docker compose up -d
```

---

### 3. Настройка Worker (Сервер скачивания)
Воркер выполняет всю ресурсоемкую работу: скачивание через `yt-dlp`, нарезку через `ffmpeg` и выгрузку в Telegram.

Склонируйте проект на Ваш pi/домашний сервер и перейдите в его директорию:
```bash
git clone https://github.com/u5lb/VidSave.git
cd VidSave
```

Перейдите в папку воркера и создайте конфиг:

```bash
cd worker/
nano .env
```

Заполните `.env` воркера:
```ini
# Строка подключения к VPS
SERVER_URL=wss://Поддомен.ВАШ_ДОМЕН/ws/worker/worker_pi?token=MySuperSecretToken20261

# Путь до контейнера локального Telegram API
TELEGRAM_API_URL=http://vidsave_telegram-api:8081

# Токен бота
BOT_TOKEN=токен_без_кавычек

#Имя пользователя бота из TG без@
BOT_USERNAME=Юзерней_бота_из_telegram

#Docker tg-api
# Получите их на сайте https://my.telegram.org
TELEGRAM_API_ID=00000000
TELEGRAM_API_HASH=000000dddaaa0000aaabbb000222ddd000

```

#### Выбор сетевой архитектуры (Важно!)
В папке `worker/` вам нужно выбрать правильную конфигурацию сети в `docker-compose.yml` в зависимости от вашего роутера и провайдера.

**Вариант А: Роутер с обходом блокировок**
Если на вашем роутере уже настроен обход блокировок на уровне всей сети (sTGWS + Zapret) используйте стандартный конфиг. В нём контейнеры просто делят общий RAM-диск.

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
Для тех, у кого роутер выполняет только самые базовые задачи, потребуется настроить обход блокировок прямо на хост-машине, разделив потоки трафика.
Логика работы этого варианта:
**YouTube (воркер)**: Трафик идет через утилиту Zapret, что позволяет обойти замедление и при этом сохранить ваш локальный резидентский IP-адрес. Это необходимо для защиты от жесткой политики YouTube в отношении IP-адресов датацентров (именно поэтому мы используем домашний сервер; если у вас есть VPS с резидентским IP или безлимитные прокси, локальный воркер не нужен).

**Telegram API**: Трафик к серверам Telegram выносится в отдельную изолированную Docker-сеть `vpn_net`, которая на уровне хоста заворачивается в туннель AmneziaWG или Xray.
Для корректной работы Docker-сети поверх VPN-туннеля необходимо жестко задать MTU 1360, иначе пакеты будут теряться. Конфигурация сети уже зашита в сам docker-compose.yml с вашей стороны останется лишь настроить конфиг amnezia или xray для маршрутизации трафика из сети `vpn_net` в тоннель.



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

---

## Пример конфигурации AmneziaVPN Для Telegram:
## Поменяйте на свои значения! Возьмите свой полученный из Amnezia VPN конфиг и добавьте недостающее.

```ini
[Interface]
Address = АЙПИ_В_ВПН_СЕТИ/24 #/24 нужно для доступка к Pi из VPN
# Закомментировано, чтобы не трогать DNS-настройки самого хоста
# DNS = 1.1.1.1, 1.0.0.1
PrivateKey = ВАШ_PRIVATE_KEY

# Отключаем вмешательство в маршрутизацию хоста
Table = off 

# Направляем трафик изолированной сети Docker (10.20.0.0/16) в VPN
PostUp = ip rule add from 10.20.0.0/16 table 120
PostUp = ip route add default dev %i table 120
PostUp = iptables -t nat -A POSTROUTING -s 10.20.0.0/16 -o %i -j MASQUERADE

# Очищаем правила при отключении туннеля
PostDown = iptables -t nat -D POSTROUTING -s 10.20.0.0/16 -o %i -j MASQUERADE
PostDown = ip route del default dev %i table 120
PostDown = ip rule del from 10.20.0.0/16 table 120

Jc = 0
Jmin = 0
Jmax = 0
S1 = 0
S2 = 0
S3 = 0
S4 = 0
H1 = 0
H2 = 0
H3 = 0
H4 = 0
HeaderProtectionKey = ВАШ_HEADER_PROTECTION_KEY
ContentPaddingAddition = 0
RekeyAfterTime = 0
RekeyTimeout = 0
RejectAfterTime = 0
KeepaliveTimeout = 0
MaxHandshakeAttempts = 0
RandomTrailers = on
DisableCookies = on

[Peer]
PublicKey = ВАШ_PUBLIC_KEY
PresharedKey = ВАШ_PRESHARED_KEY
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = IP_СЕРВЕРА:ПОРТ
PersistentKeepalive = 0
```
</details>

## Управление и логирование

Посмотреть логи процесса скачивания (yt-dlp):
```bash
cd VidSave/worker
docker logs vidsave_pi_worker -f
```

Посмотреть сетевые логи локального сервера Telegram API:
```bash
docker logs vidsave_telegram-api -f
```

Перезапустить воркер после внесения изменений в код:
```bash
docker compose up -d --build
```
