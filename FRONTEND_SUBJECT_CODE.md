# Переход фронта на `subject_code`

## Главное правило

Во всех запросах, где дисциплина является ссылкой на другую сущность, фронт отправляет
`subject_code`, а не `subject_id` и не название дисциплины. Код берётся из
`GET /schedules/lookup/subjects` или `GET /admin/subjects`.

Сопоставление и проверка дублей выполняются только по точному коду дисциплины.
Одинаковые названия с разными кодами допустимы.

## Что заменить во фронте

| Операция | Было | Стало |
|---|---|---|
| Создание дисциплины `POST /admin/subjects` | `code` | `subject_code` |
| Изменение дисциплины | `/admin/subjects/{subject_id}/patch` | `/admin/subjects/{subject_code}/patch` |
| Удаление дисциплины | `/admin/subjects/{subject_id}/delete` | `/admin/subjects/{subject_code}/delete` |
| Создание/изменение занятия | `subject_id` или `subject_title` | `subject_code` |
| Назначение дисциплин преподавателю | `subject_ids` | `subject_codes` |
| Итоговая оценка `POST /grades/final` и `/grated/final` | `subject_id` | `subject_code` |
| Изменение итоговой оценки | `/final/{student_id}/{subject_id}` | `/final/{student_id}/{subject_code}` |
| Создание материала (multipart/form-data) | `subject_id` | `subject_code` |
| Фильтры расписания, оценок и материалов | `subject_id`/`subject_title` | `subject_code` |

Для преподавателя массив выглядит так:

```json
{
  "subject_codes": ["MATH-101", "PHYS-201"]
}
```

Для занятия:

```json
{
  "group_code": "ИС-24",
  "room_code": "A-101",
  "subject_code": "MATH-101",
  "teacher_id": 12,
  "starts_at": "2026-09-01T08:30:00Z",
  "ends_at": "2026-09-01T10:00:00Z"
}
```

Для итоговой оценки:

```json
{
  "student_id": 25,
  "subject_code": "MATH-101",
  "value": "5",
  "semester": {
    "year": 2026,
    "season": "осень"
  }
}
```

Фильтры передаются query-параметром, например:

```text
GET /schedules/lessons?subject_code=MATH-101
GET /grades/export?subject_code=MATH-101
GET /materials/by_group_subject?group_id=7&subject_code=MATH-101
```

Ответы для занятий, оценок, материалов, преподавателей и справочников содержат
`subject_code`. Старые поля `subject_id`, `subject_ids` и `code` пока сохранены в части
контракта только для обратной совместимости; новый фронт не должен на них опираться.

## Сообщения об ошибках

| HTTP | `detail` / `msg` | Когда возникает |
|---:|---|---|
| 400 | `Subject already exists` | Создание дисциплины или смена кода на уже занятый код |
| 400 | `Subject not found` | В material endpoint не передан код либо код не найден |
| 400 | `Lesson teacher must match subject's primary teacher` | Преподаватель занятия не совпадает с основным преподавателем дисциплины |
| 404 | `Subject not found` | Код дисциплины не найден в JSON endpoint или path |
| 404 | `Teacher not found` | Указанный преподаватель не найден |
| 422 | `Value error, subject_code is required` | В обязательном JSON-запросе отсутствует `subject_code` |
| 422 | `Value error, subject_code and code must match` | Одновременно переданы разные `subject_code` и legacy-поле `code` |
| 422 | `Для дисциплины не настроен тип итогового контроля` | У дисциплины нет `exam` или `зачет` |
| 422 | `Тип оценки должен совпадать с типом контроля дисциплины: '<тип>'` | Передан неправильный тип итоговой оценки |
| 422 | `Для дисциплины с типом 'exam' допустимы только оценки 2, 3, 4 и 5` | Недопустимое значение экзамена |
| 422 | `Для дисциплины с типом 'зачет' допустимы только 'зачет' и 'не зачет'` | Недопустимое значение зачёта |

В `422` FastAPI возвращает массив `detail`; отображаемый текст находится в поле
`detail[n].msg`. Для остальных перечисленных ошибок текст находится в строковом
`detail`.
