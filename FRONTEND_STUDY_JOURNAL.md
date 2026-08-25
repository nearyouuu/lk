# Электронный учебный журнал — описание интеграции для frontend

Документ описывает frontend для электронного журнала и ведомости контрольных точек. Журнал работает независимо от расписания: группы, студенты и дисциплины загружаются автоматически, а преподаватель вручную создаёт занятия, выбирает или вводит тему, отмечает посещаемость и выставляет баллы.

## 1. Базовые условия

- Все запросы выполняются с `Authorization: Bearer <access_token>`.
- Базовый путь API именно для нового модуля электронного журнала: `/api/v1`. Старые модули backend могут работать без этого префикса.
- На текущем сервере приложение развёрнуто под `/lk`, поэтому полный production-префикс API: `https://ddt.donstu.ru/lk/api/v1`.
- Например, каталог журнала доступен по адресу `https://ddt.donstu.ru/lk/api/v1/journal/catalog?academic_year=2026&semester=autumn`.
- Адрес `/lk/journal/catalog` неверный: в нём отсутствует обязательный сегмент `/api/v1`.
- Префикс `/lk` должен находиться в `apiBaseUrl`. Не нужно добавлять его в каждом методе вручную.
- Формат дат: `YYYY-MM-DD`.
- Формат времени: `HH:mm:ss`.
- Семестр: `autumn` или `spring`.
- Для изменения существующих данных обязательно передавать поле `version`.
- Закрытый учебный период и заблокированная контрольная точка доступны только для чтения.

Пример настройки клиента:

```ts
const apiBaseUrl = import.meta.env.VITE_API_URL;

const api = axios.create({
  baseURL: `${apiBaseUrl}/api/v1`,
});
```

## 2. Права доступа

| Permission | Назначение |
|---|---|
| `journal.read` | Просмотр журнала и ведомости |
| `journal.lesson.write` | Создание и изменение занятий |
| `journal.entry.write` | Посещаемость и оценки |
| `journal.topic.manage` | Управление темами дисциплины |
| `journal.period.lock` | Закрытие и открытие периода |
| `journal.audit.read` | Просмотр истории изменений |

Преподаватель видит только назначенные ему пары «группа — дисциплина». Администратор и директор видят все данные. Переданный с frontend `teacher_id` не расширяет права пользователя.

## 3. Рекомендуемая структура интерфейса

Экран журнала удобно разделить на три части:

1. Фильтры: учебный год, семестр, группа, дисциплина и диапазон дат.
2. Вкладка «Учебный журнал»: студенты, занятия, темы, посещаемость и оценки.
3. Вкладка «Контрольные точки»: три КТ и итоговая рейтинговая ведомость.

Последовательность загрузки:

1. После выбора года и семестра загрузить каталог доступных групп и дисциплин.
2. После выбора группы и дисциплины параллельно загрузить журнал и контрольные точки.
3. Если контрольные точки ещё не созданы, показать действие «Сформировать КТ».

## 4. Каталог групп и дисциплин

### Запрос

```http
GET /api/v1/journal/catalog?academic_year=2026&semester=autumn
```

Администратор может дополнительно указать `teacher_id`.

### Ответ

```json
{
  "academic_year": 2026,
  "semester": "autumn",
  "groups": [
    {
      "id": 201,
      "code": "ИС-21",
      "student_count": 25,
      "subjects": [
        {
          "id": 101,
          "code": "ИТ.01",
          "title": "Информационные технологии",
          "grade_scale": "five_point"
        }
      ]
    }
  ]
}
```

Группы и дисциплины берутся из этого ответа. Не нужно заставлять преподавателя вручную создавать их в журнале.

## 5. Учебный журнал

### 5.1. Получение студентов группы

```http
GET /api/v1/journal/groups/201/students?on_date=2026-08-24
```

`on_date` нужен, чтобы учитывать состав группы на выбранную дату.

### 5.2. Получение журнала

```http
GET /api/v1/journal?group_id=201&subject_id=101&date_from=2026-09-01&date_to=2026-12-31
```

Основные разделы ответа:

```ts
type JournalResponse = {
  group: Group;
  subject: Subject;
  students: Student[];
  lessons: JournalLesson[];
  entries: JournalEntry[];
  permissions: {
    can_edit: boolean;
    can_manage_topics: boolean;
  };
  period: {
    id: number;
    is_locked: boolean;
  };
};
```

Рекомендуемое отображение: строки — студенты, столбцы — занятия. В ячейке находятся посещаемость, оценка и комментарий.

### 5.3. Создание занятия вручную

```http
POST /api/v1/journal/lessons
Idempotency-Key: 53bf1267-56bf-4e71-aa78-7b68880fc41b
Content-Type: application/json
```

```json
{
  "group_id": 201,
  "subject_id": 101,
  "date": "2026-09-07",
  "starts_at": "09:00:00",
  "ends_at": "10:30:00",
  "type": "practice",
  "topic_id": 55,
  "topic_text": null,
  "comment": null,
  "status": "published",
  "schedule_lesson_id": null
}
```

Допустимые типы занятия:

- `lecture` — лекция;
- `practice` — практическое занятие;
- `lab` — лабораторное занятие.

Тему можно указать одним из двух способов:

- `topic_id` — выбрать подготовленную тему дисциплины;
- `topic_text` — ввести свободный текст.

`schedule_lesson_id` может быть `null`: занятие не обязано быть связано с расписанием.

Для каждого нового запроса генерация `Idempotency-Key` должна выполняться на frontend. При повторной отправке того же запроса используется прежний ключ.

### 5.4. Изменение занятия

```http
PATCH /api/v1/journal/lessons/9001
```

```json
{
  "date": "2026-09-08",
  "topic_id": 56,
  "status": "published",
  "version": 3
}
```

### 5.5. Отмена занятия

```http
DELETE /api/v1/journal/lessons/9001
```

Ответ: `204 No Content`. Запись не удаляется физически, а переводится в отменённое состояние.

### 5.6. Посещаемость и оценка студента

```http
PUT /api/v1/journal/lessons/9001/entries/501
```

```json
{
  "attendance": "present",
  "grade": 5,
  "comment": null,
  "version": 0
}
```

Для новой записи передаётся `version: 0`, для существующей — версия из последнего ответа API.

Статусы посещаемости:

| Значение | Отображение |
|---|---|
| `present` | Присутствовал |
| `absent` | Отсутствовал |
| `late` | Опоздал |
| `excused` | Уважительная причина |

### 5.7. Пакетное сохранение

```http
PUT /api/v1/journal/lessons/9001/entries:batch
```

```json
{
  "entries": [
    {
      "student_id": 501,
      "attendance": "present",
      "grade": 5,
      "version": 1
    },
    {
      "student_id": 502,
      "attendance": "absent",
      "grade": null,
      "version": 0
    }
  ]
}
```

Пакетный метод возвращает отдельно `updated` и `failed`. Ошибка одной строки не означает, что остальные строки не сохранились. На frontend нужно отметить только неуспешные ячейки.

## 6. Темы дисциплины

Темы независимы от расписания и принадлежат дисциплине.

```http
GET    /api/v1/admin/subjects/101/topics?include_inactive=false
POST   /api/v1/admin/subjects/101/topics
PATCH  /api/v1/admin/subjects/101/topics/55
DELETE /api/v1/admin/subjects/101/topics/55
PUT    /api/v1/admin/subjects/101/topics:reorder
```

Пример создания темы:

```json
{
  "title": "Работа с базами данных",
  "description": null,
  "position": 1
}
```

Пример изменения порядка:

```json
{
  "topic_ids": [55, 58, 56, 57]
}
```

В интерфейсе можно использовать `select` с поиском и действием «Добавить новую тему». Если у пользователя нет `can_manage_topics`, создание и редактирование тем нужно скрыть.

## 7. Назначение преподавателя на группу и дисциплину

Эта настройка позволяет журналу работать без связи с расписанием.

```http
GET    /api/v1/admin/journal/assignments
POST   /api/v1/admin/journal/assignments
DELETE /api/v1/admin/journal/assignments/77
```

```json
{
  "teacher_id": 42,
  "group_id": 201,
  "subject_id": 101,
  "academic_year": 2026,
  "semester": "autumn"
}
```

Для администратора рекомендуется отдельная таблица назначений с фильтрами по преподавателю, группе, дисциплине и периоду.

## 8. Контрольные точки

### 8.1. Правила расчёта

В семестре формируются три контрольные точки:

| Контрольная точка | Текущий контроль | Посещаемость | Базовый максимум |
|---|---:|---:|---:|
| КТ 1 | 20 | 3 | 23 |
| КТ 2 | 20 | 3 | 23 |
| КТ 3 | 20 | 4 | 24 |
| Итого | 60 | 10 | 70 |

Дополнительно студент может получить до 20 баллов за участие в профессиональных проектах колледжа. Общий максимум за семестр — 90 баллов.

Количество занятий и позиции КТ рассчитывает backend:

```text
lessonCount = ceil(totalPracticalHours / hoursPerLesson)
interval = ceil(lessonCount / 3)
КТ 1 = interval
КТ 2 = interval × 2
КТ 3 = последнее занятие
```

Пример для 68 часов и занятия продолжительностью 4 часа: 17 занятий, КТ назначаются на 6-е, 12-е и 17-е занятие.

Frontend не должен самостоятельно повторять расчёт как источник истины. Формулу можно показать пользователю как предварительную подсказку, но позиции нужно брать из ответа API.

### 8.2. Формирование контрольных точек

```http
POST /api/v1/journal/control-points:generate
```

```json
{
  "group_id": 201,
  "subject_id": 101,
  "academic_year": 2026,
  "semester": "autumn",
  "total_practical_hours": 68,
  "hours_per_lesson": 4,
  "study_component": "discipline"
}
```

Допустимые значения `study_component`:

- `discipline`;
- `interdisciplinary_course`;
- `practice`;
- `industrial_practice` — КТ не формируются;
- `coursework` — КТ не формируются.

Пример ответа:

```json
{
  "lesson_count": 17,
  "interval": 6,
  "formula": "ceil((68/4)/3)",
  "items": [
    {
      "id": 301,
      "number": 1,
      "planned_lesson_number": 6,
      "planned_date": null,
      "current_max": 20,
      "attendance_max": 3,
      "base_max": 23,
      "project_semester_max": 20,
      "status": "draft",
      "version": 1
    }
  ]
}
```

Повторное формирование обновляет существующие незаблокированные КТ, поэтому отдельное действие «Пересчитать» может вызывать тот же endpoint.

### 8.3. Получение контрольных точек

```http
GET /api/v1/journal/control-points?group_id=201&subject_id=101&academic_year=2026&semester=autumn
```

Ответ содержит массив `items`. В каждой КТ находятся её настройки и баллы студентов.

### 8.4. Изменение контрольной точки

```http
PATCH /api/v1/journal/control-points/301
```

```json
{
  "planned_lesson_number": 6,
  "planned_date": "2026-10-05",
  "journal_lesson_id": 9001,
  "status": "published",
  "version": 1
}
```

Статусы КТ:

- `draft` — черновик;
- `published` — опубликована;
- `locked` — заблокирована для редактирования.

### 8.5. Сохранение баллов одного студента

```http
PUT /api/v1/journal/control-points/301/scores/501
```

```json
{
  "current_score": 18,
  "attendance_score": null,
  "project_score": 5,
  "comment": null,
  "version": 0
}
```

Правила полей:

- `current_score`: от 0 до 20;
- `attendance_score`: `null` означает автоматический расчёт; введённое число становится ручной корректировкой;
- `project_score`: баллы за проекты в рамках конкретной КТ;
- сумма `project_score` по трём КТ не может превышать 20;
- `version: 0` используется при первой записи баллов.

Пример объекта баллов в ответе:

```json
{
  "id": 801,
  "control_point_id": 301,
  "student_id": 501,
  "current_score": 18,
  "attendance_score": 3,
  "calculated_attendance_score": 3,
  "attendance_is_manual": false,
  "eligible_lessons": 6,
  "attended_lessons": 6,
  "project_score": 5,
  "total_score": 26,
  "comment": null,
  "version": 1
}
```

Если `attendance_is_manual === true`, рядом с баллом нужно показать признак ручной корректировки и действие «Вернуть автоматический расчёт».

### 8.6. Пакетное сохранение баллов

```http
PUT /api/v1/journal/control-points/301/scores:batch
```

```json
{
  "scores": [
    {
      "student_id": 501,
      "current_score": 18,
      "attendance_score": null,
      "project_score": 5,
      "version": 1
    },
    {
      "student_id": 502,
      "current_score": 16,
      "attendance_score": null,
      "project_score": 0,
      "version": 0
    }
  ]
}
```

Как и в журнале, ответ может содержать одновременно успешные и ошибочные строки.

### 8.7. Пересчёт посещаемости

```http
POST /api/v1/journal/control-points/301/attendance:recalculate?reset_manual=false
```

- `reset_manual=false` — пересчитать только автоматически рассчитанные значения;
- `reset_manual=true` — удалить ручные корректировки и пересчитать всех студентов.

Посещаемость считается по занятиям типов `practice` и `lab`, которые входят в соответствующий участок до КТ. Отменённые занятия не учитываются. Штраф применяется за статус `absent` пропорционально числу занятий.

## 9. Рейтинговая ведомость

```http
GET /api/v1/journal/control-points/statement?group_id=201&subject_id=101&academic_year=2026&semester=autumn
```

Структура ответа:

```ts
type ControlPointStatement = {
  group: Group;
  subject: Subject;
  period: JournalPeriod;
  maximums: {
    current: 60;
    attendance: 10;
    project: 20;
    semester_total: 90;
    control_points: [23, 23, 24];
  };
  attendance_policy: {
    type: string;
    formula: string;
    note: string;
  };
  items: Array<{
    student: Student;
    control_points: Array<{
      number: 1 | 2 | 3;
      score: ControlPointScore | null;
    }>;
    current_total: number;
    attendance_total: number;
    project_total: number;
    semester_total: number;
  }>;
};
```

Рекомендуемые столбцы таблицы:

| Студент | КТ 1, текущий | КТ 1, посещение | КТ 2, текущий | КТ 2, посещение | КТ 3, текущий | КТ 3, посещение | Проекты | Итого |
|---|---:|---:|---:|---:|---:|---:|---:|---:|

Для числовых полей использовать `step="0.01"`. Рядом с проектными баллами полезно показывать остаток: `20 − project_total`.

## 10. Закрытие периода и история изменений

```http
POST /api/v1/admin/journal/periods/17/lock
POST /api/v1/admin/journal/periods/17/unlock
```

Если `period.is_locked === true`, весь журнал и ведомость должны перейти в read-only режим.

История изменений:

```http
GET /api/v1/admin/journal/audit?lesson_id=9001&student_id=501&page=1&page_size=50
```

## 11. Обработка ошибок

Единый формат ошибки:

```json
{
  "error": {
    "code": "JOURNAL_VERSION_CONFLICT",
    "message": "Данные уже были изменены другим пользователем",
    "details": {},
    "request_id": "req_01J..."
  }
}
```

| HTTP | Пример кода | Действие frontend |
|---:|---|---|
| 400 | `JOURNAL_CONTROL_POINTS_NOT_APPLICABLE` | Показать текст ошибки в форме |
| 401 | Ошибка авторизации | Обновить токен или перейти на вход |
| 403 | `JOURNAL_ACCESS_DENIED` | Показать отсутствие доступа |
| 404 | Объект не найден | Закрыть форму и обновить данные |
| 409 | `JOURNAL_VERSION_CONFLICT` | Предложить загрузить свежие данные |
| 409 | `JOURNAL_PROJECT_SCORE_LIMIT` | Показать превышение лимита 20 баллов |
| 422 | Ошибка валидации | Подсветить соответствующие поля |
| 423 | `JOURNAL_PERIOD_LOCKED` | Перевести экран в read-only |
| 423 | `JOURNAL_CONTROL_POINT_LOCKED` | Заблокировать редактирование конкретной КТ |

Также frontend должен учитывать коды:

- `JOURNAL_ATTENDANCE_SCORE_LIMIT`;
- `JOURNAL_STUDENT_NOT_IN_GROUP`;
- `JOURNAL_TOPIC_SUBJECT_MISMATCH`;
- `JOURNAL_LESSON_DUPLICATE`.

При конфликте версии нельзя молча повторять запрос со старым значением. Нужно получить актуальную запись, показать пользователю изменения и при необходимости применить ввод повторно уже с новой `version`.

## 12. Состояния сохранения

Для каждой редактируемой ячейки рекомендуется хранить состояние:

```ts
type SaveState = "idle" | "saving" | "saved" | "error" | "conflict";
```

- После ввода можно выполнять autosave с debounce 500–800 мс.
- Пока запрос выполняется, показывать компактный индикатор сохранения.
- После ответа обновлять всю сущность из response, особенно `version` и рассчитанные поля.
- При ошибке сохранять введённое значение локально, чтобы пользователь его не потерял.
- Для пакетного запроса обрабатывать результат каждой строки отдельно.

## 13. Кэширование и обновление данных

Примеры query keys для React Query:

```ts
["journalCatalog", academicYear, semester]
["journal", groupId, subjectId, dateFrom, dateTo]
["controlPoints", groupId, subjectId, academicYear, semester]
["controlPointStatement", groupId, subjectId, academicYear, semester]
```

После изменения занятия или посещаемости обновить `journal` и ведомость. После изменения баллов КТ обновить `controlPoints` и `controlPointStatement`. После формирования или изменения КТ обновить оба запроса контрольных точек.

## 14. Минимальный объём первой версии frontend

1. Выбор учебного года, семестра, группы и дисциплины.
2. Таблица журнала со студентами и созданными занятиями.
3. Создание занятия без обязательной связи с расписанием.
4. Выбор готовой темы или ввод темы вручную.
5. Посещаемость, оценки и пакетное сохранение.
6. Формирование трёх контрольных точек.
7. Ввод текущих и проектных баллов, автоматический расчёт посещаемости.
8. Итоговая рейтинговая ведомость.
9. Read-only режим для закрытых периодов и заблокированных КТ.
10. Обработка конфликтов версий и частичных ошибок batch-запросов.
