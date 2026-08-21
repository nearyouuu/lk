# Семестр в запросах оценок

Backend принимает объект `semester` при создании обычной и итоговой оценки.

Поддерживаются оба набора URL:

- `POST /lk/grades` и совместимый alias `POST /lk/grated`;
- `POST /lk/grades/final` и совместимый alias `POST /lk/grated/final`.

Рекомендуется постепенно перейти на корректное имя `/grades`. `/grated` оставлен
для совместимости с текущим frontend.

## Формат semester

```json
{
  "year": 2026,
  "season": "весна"
}
```

`grade_type` нельзя отправлять как Swagger placeholder `"string"`. Для обычной
оценки frontend должен передавать реальный тип, например `"текущая"`. Повторная
оценка того же типа для одного занятия вернёт `409 Conflict`, а не `500`.

Допустимые значения `season`:

- `весна`;
- `осень`.

Регистр и пробелы нормализуются. Год должен находиться в диапазоне 2000–2200.

## Обычная оценка

```http
POST /lk/grated
Authorization: Bearer <token>
Content-Type: application/json
```

```json
{
  "student_id": 15,
  "teacher_id": 4,
  "lesson_id": 120,
  "grade_type": "текущая",
  "value": "5",
  "graded_at": "2026-03-12T10:30:00Z",
  "comment": null,
  "semester": {
    "year": 2026,
    "season": "весна"
  }
}
```

## Итоговая оценка

```http
POST /lk/grated/final
Authorization: Bearer <token>
Content-Type: application/json
```

```json
{
  "student_id": 15,
  "subject_id": 8,
  "value": "5",
  "comment": "Итог за семестр",
  "semester": {
    "year": 2026,
    "season": "весна"
  }
}
```

Повторный запрос с теми же `student_id`, `subject_id`, `semester.year` и
`semester.season` обновляет итоговую оценку только этого семестра. Запрос для
`2026/осень` создаёт отдельную итоговую оценку.

Ответ содержит тот же объект:

```json
{
  "id": 501,
  "student_id": 15,
  "subject_id": 8,
  "teacher_id": 4,
  "lesson_id": null,
  "grade_type": "final",
  "value": "5",
  "graded_at": "2026-05-30T09:00:00Z",
  "comment": "Итог за семестр",
  "modified_by_admin_id": null,
  "semester": {
    "year": 2026,
    "season": "весна"
  }
}
```

`semester` пока необязателен для обратной совместимости. Новому frontend следует
передавать его всегда.

## Обновление базы на клиенте

В клиентской установке используется `SKIP_MIGRATIONS=1`. В release добавлен
скрипт, который применяет SQL, проверяет колонки, пересобирает image и
пересоздаёт backend:

```bash
cd /opt/lk
chmod +x client_*.sh
./client_update.sh
```

Для принудительной чистой пересборки Docker image:

```bash
./client_update.sh --no-cache
```

Отдельные операции:

```bash
./client_apply_grade_semester.sh
./client_recreate_backend.sh
```

Скрипт обновления БД раскрывает `POSTGRES_USER` и `POSTGRES_DB` внутри
DB-контейнера, а не в shell хоста. Поэтому пользователь хоста `root` не попадёт
в команду `psql`.

Для старых клиентских схем скрипт также снимает устаревшее ограничение
`NOT NULL` с `grades.teacher_id`: администратор или директор может отправить
`teacher_id: null`.
