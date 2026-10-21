# Карта інтеграції фронтенду з API

Стан «до»: усі сторінки читали `PROJECTS` з `src/data/projects.ts`; дії (вхід, профіль, видалення акаунта)
змінювали лише React state. Тепер `PROJECTS` видалено; ці дані доступні як seed (`manage.py seed_demo`).
Статичні дані дизайну (`TYPE_META`, `SECTIONS`, кольори акцентів) залишено у `src/data/projects.ts`.

| Сторінка / компонент | Показує | Дії | API |
|---|---|---|---|
| `App.tsx` | сесія, книги для навігації, тема/мова | перевірка сесії, вихід | `GET /auth/me/`, `GET /settings/`, `GET /books/`, `POST /auth/logout/`, `PATCH /settings/` |
| `pages/Auth.tsx` | форма входу / реєстрації, помилки полів | реєстрація, вхід | `GET /auth/csrf/`, `POST /auth/register/`, `POST /auth/login/` |
| `components/Sidebar.tsx` | книги, розділи книги, користувач | глобальний пошук (debounce 300 мс, скасування) → перехід до сутності | `GET /search/?q=` |
| `pages/Library.tsx` | книги з прогресом, кількістю розділів і слів; порожній стан | створення книги (новий або наявний світ) | `GET /books/`, `GET /worlds/`, `POST /books/` |
| `pages/Overview.tsx` + `BookForm`, `WorldForm` | опис, лічильники світу, плитки розділів | редагування книги/світу, видалення книги з підтвердженням | `GET /worlds/{id}/`, `PATCH /books/{id}/`, `PATCH /worlds/{id}/`, `DELETE /books/{id}/` |
| `pages/Encyclopedia.tsx` + `EntityForms` | персонажі, фракції, лор за вкладками (Персонаж/Фракція/Локація/Предмет/Істота/Лор), пошук | створення/редагування/видалення, теги, звʼязки | `/worlds/{id}/characters/`, `/factions/`, `/lore/`, `/relationships/` |
| `pages/Characters.tsx` + `CharacterForm` | картки з портретом, статусом і фракціями | CRUD, факти, дати життя, портрет, членство, звʼязки | `/worlds/{id}/characters/`, `…/portrait/`, `/memberships/`, `/factions/`, `/relationships/` |
| `pages/Diary.tsx` | дошка з колонками й нотатками (створюється при першому відкритті) | додати/редагувати/видалити нотатку чи колонку, drag-and-drop між колонками, звʼязати нотатки | `GET/POST /boards/`, `/boards/{id}/items/`, `/boards/{id}/connections/`, `POST /boards/{id}/layout/` |
| `pages/Book.tsx` | обкладинка → список розділів, редактор або режим читання | додати/видалити/переставити розділ, імпорт/експорт DOCX | `/books/{id}/chapters/`, `…/reorder/`, `POST /import/docx/`, `GET /books/{id}/export/`, `GET …/chapters/{cid}/export/` |
| `components/ChapterEditor.tsx` | Tiptap-редактор, стан збереження, лічильник слів, підказки, правопис, метадані розділу | автозбереження (1,5 с), Ctrl+S → версія, конфлікт 409, відновлення чернетки, версії, заміна слова, словник | `PATCH/GET /books/{id}/chapters/{cid}/`, `…/versions/…`, `POST /analysis/quick-check/`, `/language/*` |
| `pages/Timeline.tsx` | події в топологічному порядку, учасники, залежності; попередження про цикл | CRUD подій, учасники з ролями, привʼязка до фракцій/лору/розділів, залежності «після» | `/worlds/{id}/timeline/`, `/dependencies/`, `GET /chronology/` |
| `pages/Analysis.tsx` (нова вкладка «Перевірка») | статус ШІ і черги, завдання з прогресом, результати за категоріями з доказами | детерміновані перевірки, постановка глибокого аналізу, скасування, рішення, пояснення, перехід до джерела | `POST /worlds/{id}/consistency/`, `/analysis/`, `…/results/`, `…/cancel/`, `PATCH /analysis/findings/{id}/`, `…/explain/`, `GET /ai/status/` |
| `pages/Profile.tsx` | імʼя, email, біографія, статистика | збереження профілю | `GET/PATCH /auth/me/`, `GET /worlds/` |
| `pages/Settings.tsx` | тема, мова, швидкі перевірки, правопис, словник, статус ШІ | перемикачі, зміна пароля, видалення акаунта з паролем | `/settings/`, `/language/dictionary/`, `/language/status/`, `/ai/status/`, `POST /auth/password/`, `DELETE /auth/me/` |

## Стан інтерфейсу

* Завантаження: `Loading`, помилки: `ErrorState` з кнопкою «Спробувати ще», порожні стани: `Empty`.
* Повідомлення: тости (успіх / помилка). Втрата зʼєднання: банер + у редакторі статус «Офлайн — чернетка в браузері»,
  автоматичне збереження після відновлення.
* Повторне відправлення: `useBusy` блокує кнопку на час запиту; мутації не повторюються автоматично
  (виняток — автозбереження розділу з `base_revision`, яке безпечно повторювати: дублікат дає 409, після чого
  вміст звіряється з сервером).
* Небезпечні дії (видалення книги/розділу/сутності/акаунта) — через діалог підтвердження.
