# Worldweaver REST API (v1)

Повна машинно-читана схема: [openapi.yaml](openapi.yaml) (генерується командою
`python manage.py spectacular --file ../docs/openapi.yaml --validate`), інтерактивно — `/api/v1/docs/`.

## Загальне

* Базовий шлях: `/api/v1/`. Формат — JSON (імпорт DOCX і портрети — `multipart/form-data`).
* Автентифікація: Django session cookie. Для `POST/PATCH/DELETE` потрібен заголовок `X-CSRFToken`
  (значення cookie `csrftoken`, яке встановлює `GET /auth/csrf/`).
* Списки пагіновані: `?page=N&page_size=M` (макс. 200), відповідь `{count, next, previous, results}`.
  Пошук `?search=…`, сортування `?ordering=…`, фільтри — див. нижче.
* Помилки завжди мають вигляд:
  ```json
  {"error": {"code": "validation_error", "message": "name: Обовʼязкове поле.", "details": {"name": ["Обовʼязкове поле."]}}}
  ```
  Коди: `validation_error` (400), `invalid_credentials` (400), `not_authenticated` (403), `permission_denied` (403),
  `not_found` (404), `conflict` (409), `service_unavailable` (503), `server_error` (500, без внутрішніх деталей).
* Чужі обʼєкти повертають 404 (не 403), щоб не розкривати їх існування.

## Ресурси

| Метод і шлях | Опис |
|---|---|
| `GET /auth/csrf/` | Встановити cookie `csrftoken` |
| `POST /auth/register/` `{name, email, password}` | Реєстрація + вхід (201) |
| `POST /auth/login/` `{email, password}` · `POST /auth/logout/` | Вхід / вихід |
| `GET/PATCH /auth/me/` · `DELETE /auth/me/` `{password}` | Профіль; видалення акаунта (каскадно з усіма даними) |
| `POST /auth/password/` `{old_password, new_password}` | Зміна пароля |
| `GET/POST/DELETE /auth/me/avatar/` | Приватна аватарка (клієнт обрізає до квадрата, сервер перекодовує до ≤1024 px) |
| `GET/PATCH /settings/` | `theme`, `language`, `quick_checks_enabled`, `spellcheck_enabled` |
| `GET /search/?q=` | Глобальний пошук по книгах і всіх світах користувача |
| `GET/POST /worlds/` · `GET/PATCH/DELETE /worlds/{id}/` | Світи (з лічильниками). Фільтр `genre`, пошук |
| `GET /worlds/{id}/search/?q=` | Пошук персонажів, фракцій, лору, подій, розділів у світі |
| `/worlds/{id}/characters/` (+ `{cid}/`) | CRUD персонажів. Фільтри `status`, `faction`; пошук по імені, псевдонімах, біографії |
| `GET/POST/DELETE /worlds/{id}/characters/{cid}/portrait/` | Приватний портрет (JPEG/PNG/WEBP, ≤3 МБ, перекодовується) |
| `/worlds/{id}/factions/` | CRUD фракцій (`members_count`) |
| `/worlds/{id}/memberships/` | Історичне членство персонажів у фракціях (`start_key/end_key`) |
| `/worlds/{id}/lore/` | CRUD лору. Фільтри `category`, `tag`; пошук по назві, тексту, тегах |
| `/worlds/{id}/timeline/` | Події з учасниками (`participants: [{character, role}]`), фракціями, лором, розділами |
| `/worlds/{id}/dependencies/` | Часові залежності «A до B» (цикли відхиляються) |
| `GET/PUT /worlds/{id}/graph-layout/{factions|relations}/` | Збережені позиції вузлів графа `{"character:1": [x, y]}` |
| `GET /worlds/{id}/chronology/` | Топологічний порядок подій, ребра, наявність циклу |
| `/worlds/{id}/relationships/` | Типізовані звʼязки `{kind, source: {type, id}, target: {type, id}, …}`; фільтр `entity_type`+`entity_id`, `kind` |
| `GET/POST /worlds/{id}/pages/` | Сторінки енциклопедії (список без тексту; `?search=` по назві, іншим назвам і тексту, `?page_type=`, `?parent=root|<id>`). `POST {title, parent?, template?, user_template?, page_type?}` |
| `GET/PATCH/DELETE /worlds/{id}/pages/{pid}/` | Сторінка з текстом, властивостями, хлібними крихтами, дочірніми, зворотними й битими посиланнями. `PATCH {title, icon, page_type, aliases, content, base_revision}` (409 при конфлікті). `DELETE ?children=lift|delete` (без вибору — 400, якщо є підсторінки) |
| `POST /worlds/{id}/pages/{pid}/move/` `{parent, position?}` | Переміщення в дереві (цикли відхиляються) |
| `GET /worlds/{id}/pages/lookup/?q=` | Швидкий пошук сторінок для вставлення посилання |
| `GET /worlds/{id}/pages/by-entity/?type=character|faction|lore&id=` | Сторінка структурованого запису (створюється за потреби) |
| `POST /worlds/{id}/pages/{pid}/save-as-template/` · `GET /page-templates/?world=` · `DELETE /page-templates/{id}/` | Шаблони: стандартні + власні |
| `GET/POST/DELETE /worlds/{id}/pages/{pid}/cover/` | Обкладинка сторінки |
| `POST/PATCH/DELETE /worlds/{id}/pages/{pid}/properties/` (+ `{prop}/`, `reorder/`) | Властивості: `text`, `number`, `date {label, key}`, `checkbox`, `tags`, `page`, `pages` (лише сторінки того самого світу) |
| `GET /books/{id}/chapters/{cid}/relevant-pages/` | Сторінки, згадані в розділі (назви й інші назви з урахуванням відмінювання) |
| `POST /worlds/{id}/consistency/` `{book?}` | Детерміновані перевірки (синхронно), повертає завершене завдання |
| `GET/POST /books/` · `/books/{id}/` | Книги (`world` або `new_world_name` при створенні); прогрес, слова |
| `GET /books/{id}/export/` | Експорт книги в DOCX |
| `GET/POST/DELETE /books/{id}/cover/` | Приватна обкладинка (клієнт обрізає до 3:4, сервер перекодовує до ≤1600 px) |
| `GET /books/{id}/manuscript/` | Рукопис як текст по розділах |
| `/books/{id}/chapters/` (+ `{cid}/`) | Розділи; `PATCH` з `content` (Tiptap JSON), `base_revision` → 409 при конфлікті, `snapshot` |
| `POST /books/{id}/chapters/reorder/` `{order: [ids]}` | Перестановка розділів |
| `GET /books/{id}/chapters/{cid}/versions/` · `…/versions/{vid}/` · `POST …/versions/{vid}/restore/` | Версії розділу |
| `GET /books/{id}/chapters/{cid}/export/` | Експорт розділу в DOCX |
| `POST /import/docx/` `file, book, mode, chapter?, split_level?` | `mode`: `new_chapter`, `split_headings`, `replace_chapter`; `split_level` 1–3 (за замовчуванням — найвищий рівень заголовка, що трапляється ≥2 разів; стиль Title не ріже; заголовки без тексту переходять у наступний розділ) |
| `POST /import/docx/preview/` `file, split_level?` | сухий прогін: `levels`, `split_level`, `suggested_level`, `chapters[{title, word_count, merged, lead_in}]`, нічого не зберігає |
| `GET /worlds/{id}/members/` · `PATCH/DELETE …/members/{uid}/` · `GET …/members/{uid}/avatar/` | Учасники світу та їхні ролі; `DELETE` своєї id — покинути проєкт (див. docs/COLLABORATION.md) |
| `POST /worlds/{id}/transfer/` `{user}` | Передати власність учаснику (лише власник; колишній власник стає адміністратором) |
| `GET/POST /worlds/{id}/invites/` · `DELETE …/invites/{iid}/` | Запрошення: `email?`, `role`, `expires_in_days?`, `max_uses?` (адміністратори й власник); відкликання |
| `GET /invites/mine/` · `GET /invites/{token}/` · `POST /invites/{token}/accept/` · `POST …/decline/` | Особисті запрошення, перегляд, прийняття, відмова |
| `/worlds/{id}/comments/` (`?chapter=` / `?page=`) · `GET /worlds/{id}/comment-counts/?book=` | Коментарі до розділів і сторінок (від коментатора); лічильники відкритих обговорень |
| `GET/PATCH /worlds/{id}/public/` | Публічний сайт (лише власник): `enabled`, `regenerate`, позначки `books` / `chapters` / `pages` `{id: bool}` |
| `GET /public/{token}/` · `…/chapters/{id}/` · `…/pages/{id}/` · `…/images/{kind}/{id}/` | Анонімний перегляд лише позначених книг, розділів і сторінок |
| `/boards/` (`?book=` / `?world=`) · `POST /boards/{id}/layout/` | Дошки; збереження позицій/порядку/колонок пакетом |
| `/boards/{id}/items/` · `/boards/{id}/connections/` | Елементи й зʼєднання дошки |
| `GET/POST /analysis/` · `GET /analysis/{id}/` | Завдання глибокого аналізу (`kind`: `fragment`, `chapter`, `book`, `book_with_lore`) — 202 |
| `GET /analysis/{id}/results/` | Результати з доказами (фільтри `category`, `decision`, `severity`, `source`) |
| `POST /analysis/{id}/cancel/` | Скасування (у черзі — одразу; виконується — кооперативно) |
| `GET/PATCH /analysis/findings/{id}/` | Рішення автора: `decision`, `decision_note` |
| `POST /analysis/findings/{id}/explain/` | Пояснення від локальної моделі (503, якщо недоступна) |
| `POST /analysis/quick-check/` `{chapter, text, offset}` | Режим A: швидкі перевірки фрагмента без LLM |
| `GET /ai/status/` | Стан Ollama та черги |
| `POST /language/spellcheck/` `{text, world?}` · `GET /language/suggest/?word=` · `GET /language/status/` | Правопис |
| `GET/POST/DELETE /language/dictionary/` | Словник користувача |

## Приклад результату аналізу

```json
{
  "rule": "death_then_alive", "category": "potential", "severity": "warning", "source": "text",
  "summary": "Каель: загибель у «Розділ 1», але діє в «Розділ 2»",
  "manuscript_quote": "— Ходімо, — сказав Каель і рушив до брами", "position_start": 0, "position_end": 41,
  "quote_verified": true, "decision": "new",
  "evidence": [
    {"source_type": "chapter", "source_id": 1, "source_label": "Розділ 1", "quote": "Каель загинув біля воріт Берега Тиші", "verified": true},
    {"source_type": "chapter", "source_id": 2, "source_label": "Розділ 2", "quote": "— Ходімо, — сказав Каель і рушив до брами", "verified": true}
  ]
}
```
