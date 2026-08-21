# Nginx: исправление refresh на frontend-маршрутах

## Симптом

При переходе внутри SPA страница `/admin` работает, но после обновления браузера
возвращается:

```json
{"detail":"Not Found"}
```

Это означает, что Nginx отправляет `/admin` в FastAPI. Для SPA такой URL должен
возвращать frontend `index.html`, после чего маршрут разбирает frontend-router.

## Маршрутизация

- `/lk/*` — backend API;
- `/media/*` — файлы backend;
- `/assets/*` — статические ресурсы frontend;
- все остальные пути, включая `/admin`, `/director` и `/login`, — frontend SPA.

В проекте есть два разных конфига:

- `docker/nginx.conf` — полный конфиг с `events {}` и `http {}`; его можно
  монтировать только в `/etc/nginx/nginx.conf`;
- `docker/nginx.default.conf` — только блок `server {}`; его нужно монтировать в
  `/etc/nginx/conf.d/default.conf`.

Нельзя монтировать `docker/nginx.conf` в `/etc/nginx/conf.d/default.conf`: Nginx
завершится с ошибкой `events directive is not allowed here`.

## Установка на сервере

Сначала найти активный конфиг и document root:

```bash
sudo nginx -T | grep -nE 'server_name|root |location /|proxy_pass|try_files'
```

Скопировать новый конфиг в используемый Nginx. Если Nginx установлен на хосте:

```bash
sudo cp docker/nginx.conf /etc/nginx/nginx.conf
sudo nginx -t
sudo systemctl reload nginx
```

Если Nginx работает в Docker, рекомендуемый вариант для
`docker-compose.nginx.yml`:

```yaml
services:
  nginx:
    volumes:
      - ./docker/nginx.default.conf:/etc/nginx/conf.d/default.conf:ro
```

Альтернативный корректный вариант с полным конфигом:

```yaml
services:
  nginx:
    volumes:
      - ./docker/nginx.conf:/etc/nginx/nginx.conf:ro
```

Использовать одновременно оба варианта не требуется.

Текущие bind mounts контейнера можно посмотреть так:

```bash
docker inspect lk-nginx-1 \
  --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'
```

Проверка конфига и пересоздание контейнера:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.nginx.yml \
  run --rm --no-deps nginx nginx -t

docker compose \
  -f docker-compose.yml \
  -f docker-compose.nginx.yml \
  up -d --force-recreate nginx
```

Собранный frontend должен находиться в `/usr/share/nginx/html` и содержать:

```text
/usr/share/nginx/html/index.html
/usr/share/nginx/html/assets/
```

Проверка:

```bash
curl -I http://127.0.0.1/admin
curl -I http://127.0.0.1/director
curl -I http://127.0.0.1/lk/ping
```

Для `/admin` и `/director` ожидается `200` и `Content-Type: text/html`. Для
`/lk/ping` ожидается ответ backend, а не `index.html`.

## Важно для frontend

Production API base URL должен содержать `/lk`, например:

```text
http://217.175.47.66/lk
```

Вызовы API без `/lk` будут конфликтовать с frontend history routes.
