# On-premise deployment: автоматизированный runbook

Весь основной процесс вынесен в Bash-скрипты. Приватный ключ
`license_private.pem` всегда остаётся на build-сервере. Клиент получает только:

- `lk-ubuntu-release.tar.gz`;
- `cabinet_schema.sql`;
- `client_first_install.sh`;
- `client_upgrade_release.sh` для обновления существующей установки;
- после получения fingerprint — `license.lic` и `license_public.pem`.

## 1. Сборка пакета на build-сервере

```bash
cd /var/lk
chmod +x scripts/deployment/*.sh
./scripts/deployment/build_release_package.sh
```

По умолчанию схема экспортируется из контейнера `cabinet-db`, БД `cabinet`,
пользователь `cabinet`. Параметры можно переопределить:

```bash
DB_CONTAINER=my-postgres DB_USER=cabinet DB_NAME=cabinet \
  ./scripts/deployment/build_release_package.sh
```

Если схема уже подготовлена отдельно:

```bash
./scripts/deployment/build_release_package.sh --skip-schema
```

Скрипт:

1. собирает Linux binary через Docker/Nuitka;
2. извлекает release;
3. добавляет публичный ключ и пустой placeholder лицензии;
4. проверяет отсутствие приватного ключа;
5. создаёт `lk-ubuntu-release.tar.gz`;
6. экспортирует только DDL в `cabinet_schema.sql` и проверяет отсутствие данных;
7. кладёт рядом bootstrap-скрипт `client_first_install.sh`.

## 2. Первая установка у клиента

Скопировать три файла в один каталог сервера и запустить:

```bash
chmod +x client_first_install.sh
sudo ./client_first_install.sh --confirm-reset-db
```

Другой каталог установки или расположение файлов:

```bash
sudo ./client_first_install.sh \
  --archive /tmp/lk-ubuntu-release.tar.gz \
  --schema /tmp/cabinet_schema.sql \
  --install-dir /opt/lk \
  --confirm-reset-db
```

Флаг `--confirm-reset-db` обязателен: первоначальная установка удаляет схему
`public` в новой клиентской БД перед загрузкой чистой структуры. Скрипт
откажется распаковывать release в непустой `/opt/lk`.

Скрипт автоматически:

- распаковывает release;
- генерирует пароль PostgreSQL и JWT secret;
- создаёт защищённый `.env`;
- запускает PostgreSQL;
- загружает чистую схему;
- собирает и запускает backend;
- выводит `/license/status` с fingerprint клиента.

## 3. Выпуск лицензии на build-сервере

Fingerprint брать целиком из результата предыдущего шага.

```bash
cd /var/lk
./scripts/deployment/issue_client_license.sh \
  --customer 'Название организации; ИНН ...' \
  --fingerprint 'sha256:ВСТАВИТЬ_FINGERPRINT' \
  --license-id 'LIC-2026-CLIENT-0001' \
  --tariff premium \
  --expires-at '2027-08-31T20:59:59Z' \
  --max-users 500 \
  --output /var/lk/license.lic
```

Если ключи ещё ни разу не создавались, к команде добавляется `--generate-keys`.
Флаг сработает только при отсутствии обоих файлов ключей и не даст случайно
заменить существующую пару. Клиенту передаются только `license.lic` и
`license_public.pem`. `license_private.pem` не передавать.

## 4. Установка лицензии у клиента

По умолчанию скрипт ожидает файлы в `/tmp`:

```bash
cd /opt/lk
sudo ./client_install_license.sh
```

Либо указать пути явно:

```bash
sudo ./client_install_license.sh /tmp/license.lic /tmp/license_public.pem
```

Скрипт устанавливает правильные permissions, перезапускает backend и проверяет
`/license/status`. Ожидается `"valid": true`.

## 5. Создание начальных пользователей

```bash
cd /opt/lk
./client_create_initial_users.sh
```

Создаются или обновляются:

- `admin@example.kz`;
- `teacher@example.kz`;
- `student@example.kz`.

Случайные пароли выводятся один раз в терминал и не записываются в файл.
Повторный запуск изменит пароли этих аккаунтов.

## 6. Проверка установки

```bash
cd /opt/lk
./client_check.sh
```

Проверяются контейнеры, backend logs, `/ping`, лицензия, таблицы, количество
пользователей, отсутствие host port у PostgreSQL и отсутствие приватного ключа.

## 7. Backup базы

```bash
cd /opt/lk
./client_backup_db.sh
```

По умолчанию создаётся файл вида `cabinet-2026-08-13_14-30-00.dump`. Можно
указать путь:

```bash
./client_backup_db.sh /secure/backups/cabinet.dump
```

## 8. Обновление существующей установки

На build-сервере сначала собрать новый release по шагу 1. Клиенту передать:

- `lk-ubuntu-release.tar.gz`;
- `client_upgrade_release.sh`.

На клиентском сервере положить их в `/tmp` и выполнить:

```bash
chmod +x /tmp/client_upgrade_release.sh
sudo /tmp/client_upgrade_release.sh \
  --archive /tmp/lk-ubuntu-release.tar.gz \
  --install-dir /opt/lk
```

Для полной пересборки Docker image без cache:

```bash
sudo /tmp/client_upgrade_release.sh --no-cache
```

Скрипт перед обновлением создаёт backup в `/opt/lk/backups`, затем заменяет
файлы приложения, применяет миграцию и пересоздаёт только backend. Он сохраняет:

- `.env`;
- `license.lic`;
- `license_public.pem`;
- PostgreSQL volume и все данные;
- конфигурацию Nginx, если она лежит отдельным compose-файлом.

Если новые файлы release уже вручную размещены в `/opt/lk`, можно выполнить
только миграцию и пересборку:

```bash
cd /opt/lk
./client_update.sh
```

Чистая пересборка Docker image:

```bash
./client_update.sh --no-cache
```

Внутри `client_update.sh` последовательно запускаются
`client_apply_grade_semester.sh` и `client_recreate_backend.sh`.

`client_first_install.sh` при обновлении запускать нельзя: он предназначен только
для чистой установки и пересоздаёт схему `public`.

## 9. Nginx и SPA routing

Nginx клиента подключён отдельным compose-файлом. Для его пересоздания нужно
указывать оба файла:

```bash
cd /opt/lk
docker compose \
  -f docker-compose.yml \
  -f docker-compose.nginx.yml \
  up -d --force-recreate nginx
```

Если volume направлен в `/etc/nginx/conf.d/default.conf`, его source должен быть
`./docker/nginx.default.conf`, содержащий только блок `server {}`. Полный
`./docker/nginx.conf` допустимо монтировать только в `/etc/nginx/nginx.conf`.

Подробнее: `NGINX_SPA_ROUTING.md`.

## Требования безопасности

- backend публикуется только на `127.0.0.1`;
- PostgreSQL не имеет host port;
- наружу публикуется только Nginx `80/443`;
- `.env` и `license.lic` имеют permissions `600`;
- `license_private.pem` отсутствует на клиенте;
- `client_first_install.sh` нельзя применять к рабочей установке: он предназначен
  только для новой БД.
