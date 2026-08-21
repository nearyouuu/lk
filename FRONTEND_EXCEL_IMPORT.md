# Массовый импорт из Excel — интеграция frontend

## Что изменилось

Backend поддерживает массовый импорт из одного Excel-файла:

- пользователей: студентов, преподавателей, директоров и администраторов;
- групп;
- подразделений с иерархией;
- аудиторий;
- дисциплин и типов дисциплин;
- связей дисциплин с основным и дополнительными преподавателями;
- связи преподавателя с подразделением.

Каждый тип данных находится на отдельном листе. Можно импортировать только один
справочник: остальные листы разрешается не добавлять либо оставить пустыми.

## Доступ

Загрузка доступна пользователям с ролью:

- `administrator`;
- `director`.

В запросе импорта обязателен JWT:

```http
Authorization: Bearer <access_token>
```

При отсутствии или истечении токена backend отвечает `401`, при неподходящей
роли — `403`.

## API

Приложение доступно и без префикса, и через `/lk`. На клиентском стенде следует
использовать настроенный API base URL. Примеры ниже приведены с префиксом `/lk`.

### Скачать шаблон

```http
GET /lk/admin/users/import/template
```

Успешный ответ:

- статус `200`;
- Content-Type:
  `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`;
- файл `excel_import_template.xlsx`.

Эта ручка сейчас не требует роли. Скачанный backend-шаблон является источником
актуальных названий листов и колонок. Не следует собирать шаблон на frontend.

### Загрузить файл

```http
POST /lk/admin/users/import/
Content-Type: multipart/form-data
Authorization: Bearer <access_token>
```

Поле формы:

| Поле | Тип | Обязательно | Описание |
|---|---|---:|---|
| `file` | File | да | `.xls` или `.xlsx`, максимум 10 МБ |

Важно: `Content-Type` с boundary должен сформировать браузер. Не нужно задавать
`multipart/form-data` вручную при использовании `FormData`.

Успешный ответ — бинарный Excel-файл `результат_импорта.xlsx` с построчным
отчётом. Это не JSON.

## Пример на TypeScript

```ts
type ImportSummary = {
  usersCreated: number;
  usersSkipped: number;
  failed: number;
  groupsCreated: number;
  subdivisionsCreated: number;
  roomsCreated: number;
  subjectsCreated: number;
  subjectTypesCreated: number;
};

const readCount = (headers: Headers, name: string): number =>
  Number(headers.get(name) ?? 0);

export async function importExcel(
  apiBaseUrl: string,
  token: string,
  file: File,
): Promise<ImportSummary> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${apiBaseUrl}/admin/users/import/`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
    },
    body: formData,
  });

  if (!response.ok) {
    let message = "Не удалось выполнить импорт";
    try {
      const body = (await response.json()) as { detail?: string };
      message = body.detail || message;
    } catch {
      // Ответ может не содержать JSON.
    }
    throw new Error(message);
  }

  const report = await response.blob();
  const url = URL.createObjectURL(report);
  const link = document.createElement("a");
  link.href = url;
  link.download = "результат_импорта.xlsx";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);

  return {
    usersCreated: readCount(response.headers, "X-Import-Created"),
    usersSkipped: readCount(response.headers, "X-Import-Skipped"),
    failed: readCount(response.headers, "X-Import-Failed"),
    groupsCreated: readCount(response.headers, "X-Import-Groups-Created"),
    subdivisionsCreated: readCount(
      response.headers,
      "X-Import-Subdivisions-Created",
    ),
    roomsCreated: readCount(response.headers, "X-Import-Rooms-Created"),
    subjectsCreated: readCount(response.headers, "X-Import-Subjects-Created"),
    subjectTypesCreated: readCount(
      response.headers,
      "X-Import-Subject-Types-Created",
    ),
  };
}
```

Шаблон следует скачивать как бинарный `Blob`. Так frontend не сохранит JSON-ответ
с ошибкой под расширением `.xlsx`:

```ts
export async function downloadImportTemplate(apiBaseUrl: string): Promise<void> {
  const response = await fetch(`${apiBaseUrl}/admin/users/import/template`);

  if (!response.ok) {
    let message = "Не удалось скачать Excel-шаблон";
    try {
      const body = (await response.json()) as { detail?: string };
      message = body.detail || message;
    } catch {
      // Ответ может не содержать JSON.
    }
    throw new Error(message);
  }

  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("spreadsheetml.sheet")) {
    throw new Error("Сервер вернул ответ, не являющийся Excel-файлом");
  }

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "excel_import_template.xlsx";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
```

Для Axios обязательно указать `responseType: "blob"`:

```ts
const response = await axios.get(
  `${apiBaseUrl}/admin/users/import/template`,
  { responseType: "blob" },
);
```

## Сводка в response headers

После успешного импорта backend возвращает следующие заголовки:

| Header | Значение |
|---|---|
| `X-Import-Created` | создано пользователей |
| `X-Import-Skipped` | пропущено существующих пользователей |
| `X-Import-Failed` | количество ошибочных строк на всех листах |
| `X-Import-Groups-Created` | создано групп |
| `X-Import-Subdivisions-Created` | создано подразделений |
| `X-Import-Rooms-Created` | создано аудиторий |
| `X-Import-Subjects-Created` | создано дисциплин |
| `X-Import-Subject-Types-Created` | автоматически создано типов дисциплин |

Backend перечисляет эти заголовки и `Content-Disposition` в
`Access-Control-Expose-Headers`, поэтому frontend может читать их и при
cross-origin запросах. Полный результат также есть в скачиваемом Excel-отчёте.

## Структура входного Excel

Названия листов и колонок нельзя изменять. Пустые строки разрешены.

### Лист `Пользователи`

| Колонка | Обязательно | Когда используется |
|---|---:|---|
| `ФИО` | да | для всех ролей |
| `Электронная почта` | да | уникальный логин пользователя |
| `Роль` | да | `студент`, `преподаватель`, `директор`, `администратор` |
| `Телефон` | нет | для всех ролей |
| `Дата рождения` | нет | рекомендуемый формат `YYYY-MM-DD` |
| `Группа` | для студента | код группы либо `код, название` |
| `Подразделение` | нет | код или точное название подразделения преподавателя |
| `Предмет` | нет | текстовое поле профиля преподавателя |
| `Номер зачётки` | нет | для студента |
| `Год поступления` | нет | для студента |
| `Курс` | нет | для студента |

Если группы студента ещё нет, она будет создана автоматически.

### Лист `Группы`

| Колонка | Обязательно | Описание |
|---|---:|---|
| `Код группы` | да | уникальный код |
| `Название группы` | нет | при отсутствии используется код |

### Лист `Подразделения`

| Колонка | Обязательно | Описание |
|---|---:|---|
| `Код подразделения` | нет | рекомендуется для связей и иерархии |
| `Название подразделения` | да | название подразделения |
| `Тип подразделения` | нет | например `кафедра`, `деканат`, `отдел` |
| `Код родительского подразделения` | нет | код родителя из файла или базы |

Строки подразделений могут идти в любом порядке. Родитель назначается после
создания всех подразделений листа.

### Лист `Аудитории`

| Колонка | Обязательно | Описание |
|---|---:|---|
| `Код аудитории` | да | уникальный код |
| `Название аудитории` | нет | при отсутствии используется код |
| `Вместимость` | нет | положительное целое число |

### Лист `Дисциплины`

| Колонка | Обязательно | Описание |
|---|---:|---|
| `Код дисциплины` | нет | код дисциплины |
| `Название дисциплины` | да | уникальное название |
| `Тип дисциплины` | нет | отсутствующий тип создаётся автоматически |
| `Email основного преподавателя` | нет | email существующего или импортируемого преподавателя |
| `Email преподавателей` | нет | несколько email через `,` или `;` |

## Порядок обработки

Backend обрабатывает данные в таком порядке:

1. подразделения;
2. группы;
3. пользователи;
4. аудитории;
5. дисциплины.

Поэтому дисциплина может ссылаться на преподавателя, созданного в том же файле,
а преподаватель — на подразделение из того же файла.

## Поведение при дублях и ошибках

- существующие пользователи, группы, подразделения, аудитории и дисциплины не
  создаются повторно;
- ошибка одной строки не останавливает обработку остальных строк;
- итоговый файл содержит листы `Пользователи`, `Группы`, `Подразделения`,
  `Аудитории`, `Дисциплины`;
- для каждой входной строки указаны статус и комментарий;
- пароли возвращаются только для успешно созданных пользователей;
- если произошла системная ошибка всего импорта, изменения откатываются.

## Ошибки HTTP

| Статус | Причина | Действие frontend |
|---:|---|---|
| `400` | неверное расширение, пустой/повреждённый файл, неизвестные листы или обязательные колонки | показать `detail` из JSON |
| `401` | токен отсутствует или истёк | отправить пользователя на авторизацию |
| `403` | роль не `administrator`/`director` либо функция ограничена лицензией | показать сообщение о недостатке доступа |
| `404` | шаблон отсутствует на сервере | показать ошибку скачивания шаблона |
| `413` | файл больше 10 МБ | предложить уменьшить файл |
| `500` | внутренняя ошибка импорта | показать общее сообщение и предложить повторить |

Стандартное тело ошибки FastAPI:

```json
{
  "detail": "Описание ошибки"
}
```

## Рекомендуемый интерфейс

1. Показывать кнопку `Скачать шаблон`.
2. Разрешать выбор только `.xls,.xlsx`.
3. До отправки проверять размер `file.size <= 10 * 1024 * 1024`.
4. Во время запроса блокировать повторную отправку и показывать progress state.
5. После `200` автоматически скачивать отчёт, даже если `X-Import-Failed > 0`.
6. Показывать краткую сводку из response headers, если браузер имеет к ним доступ.
7. После импорта обновлять списки пользователей и соответствующих справочников.

Пример file input:

```tsx
<input
  type="file"
  accept=".xls,.xlsx,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
/>
```
