# Скрипты обновления клиентского backend

В Ubuntu release включены четыре исполняемых скрипта:

| Файл | Назначение |
|---|---|
| `client_apply_grade_semester.sh` | применяет идемпотентный SQL и проверяет новые колонки |
| `client_recreate_backend.sh` | пересобирает image и пересоздаёт backend-контейнер |
| `client_update.sh` | последовательно выполняет обе операции |
| `client_upgrade_release.sh` | обновляет установленный release с автоматическим backup и сохранением конфигурации |

Ожидаемая версия схемы не зашита в update-скрипт. При сборке release текущий
единственный Alembic head автоматически записывается в `alembic_head.txt`, после
запуска backend скрипт сравнивает с ним значение из таблицы `alembic_version`.

## Обновление из нового release archive

```bash
chmod +x /tmp/client_upgrade_release.sh
sudo /tmp/client_upgrade_release.sh \
  --archive /tmp/lk-ubuntu-release.tar.gz \
  --install-dir /opt/lk
```

Этот вариант используется для обычного обновления уже установленного клиента.
`.env`, лицензия и PostgreSQL volume сохраняются.

## Обычное обновление

```bash
cd /opt/lk
chmod +x client_*.sh
./client_update.sh
```

Если release находится в `/var/lk`, команда аналогична:

```bash
cd /var/lk
chmod +x client_*.sh
./client_update.sh
```

## Чистая пересборка image

```bash
./client_update.sh --no-cache
```

## Только обновление БД

```bash
./client_apply_grade_semester.sh
```

SQL можно применять повторно: используются `IF NOT EXISTS` и проверка результата.
Параметры подключения берутся внутри контейнера `db`, поэтому переменные shell
хоста и пользователь `root` не используются.

## Только пересоздание backend

```bash
./client_recreate_backend.sh
```

Или без Docker build cache:

```bash
./client_recreate_backend.sh --no-cache
```

Скрипты сами определяют `docker compose` или старую команду `docker-compose`, а
также рабочий каталог — они работают и из release root, и из каталога `scripts`.
