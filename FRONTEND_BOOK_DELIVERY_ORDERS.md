# Заявки на привоз книг через `document-orders`

## Создание заявки студентом

```http
POST /document-orders
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "order_type": "book_delivery",
  "request_text": "Прошу привезти книгу по анатомии"
}
```

`request_text` обязателен, обрезается по краям и ограничен 2000 символами.
`student_id`, ФИО и группа берутся backend'ом из профиля студента.
Поля справок (`certificate_type`, `department`, `copies_count` и другие) отправлять
для `book_delivery` не нужно.

В ответе поля справки имеют значение `null`, а также возвращаются:

```json
{
  "order_type": "book_delivery",
  "request_text": "Прошу привезти книгу по анатомии",
  "status": "new"
}
```

Старые заявки на справки имеют `order_type: "certificate"`.

## Фильтры администратора

```http
GET /document-orders?order_type=book_delivery&status=new&created_from=2026-08-10&created_to=2026-08-17&group_name=СД-21&q=анатомия
Authorization: Bearer <access_token>
```

Поддерживаются параметры:

- `order_type`: `certificate` или `book_delivery`;
- `status`;
- `created_from`, `created_to` в формате `YYYY-MM-DD`;
- `group_name`;
- `student_id`;
- `q`: поиск по ФИО, группе и тексту заявки.

## Прямое скачивание администратором

```http
GET /document-orders/export?status=new&created_from=2026-08-10&created_to=2026-08-17&q=анатомия
Authorization: Bearer <access_token>
```

Endpoint доступен только роли `administrator` и всегда выгружает только заявки
`book_delivery`. Ответ — XLSX-файл.

## Создание ссылки для скачивания без авторизации

Ссылку может создать только администратор:

```http
POST /document-orders/export-links
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "status": "new",
  "created_from": "2026-08-10",
  "created_to": "2026-08-17",
  "group_name": "СД-21",
  "q": "анатомия",
  "expires_in_hours": 168
}
```

Все фильтры необязательны. `expires_in_hours` — от 1 до 168 часов, по умолчанию
168 часов.

Ответ:

```json
{
  "url": "https://example.ru/lk/document-orders/public-export/<signed-token>",
  "expires_at": "2026-08-24T12:00:00Z"
}
```

Полученный `url` открывается обычной ссылкой без `Authorization` и сразу скачивает
XLSX. Фронту не нужно самостоятельно добавлять token или query-параметры.

Ссылка подписана и привязана к выбранным фильтрам. Изменить фильтры внутри готовой
ссылки нельзя. После истечения срока backend возвращает:

```json
{
  "detail": "Ссылка на выгрузку недействительна или истекла"
}
```

Любой человек, получивший действующую ссылку, сможет скачать файл. Поэтому её нельзя
публиковать в открытом доступе. Для новой выборки или нового срока администратор
создаёт новую ссылку.

## Изменения интерфейса

Для студента:

- добавить карточку «Привоз книги»;
- показать textarea с `maxlength=2000`;
- отправлять только `order_type` и `request_text`;
- в истории различать `certificate` и `book_delivery`.

Для администратора:

- добавить вкладку с фильтром `order_type=book_delivery`;
- добавить фильтры статуса, периода, группы и поиска;
- добавить кнопки «Скачать XLSX» и «Создать ссылку»;
- после создания ссылки показывать срок действия и кнопку копирования.

## Настройка backend

Перед развёртыванием выполнить миграцию:

```bash
alembic upgrade head
```

В production задать отдельный случайный секрет длиной не менее 32 байт:

```env
EXPORT_LINK_SECRET=<random-secret>
```
