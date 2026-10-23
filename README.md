# Worldweaver

Робочий простір для письменників і сценаристів: книги й розділи з редактором, світи з лором,
персонажами, фракціями та хронологією, дошка ідей і пошук сюжетних суперечностей — детермінованими
правилами та ШІ **Google Gemini**. Детерміновані перевірки працюють локально; для пошуку ляпів ШІ текст
розділів надсилається в Google (див. розділ 4).

| Частина | Технології |
|---|---|
| `Backend/` | Python 3.12, Django 5.2 LTS, Django REST Framework, PostgreSQL (SQLite — лише для швидких тестів), drf-spectacular, python-docx, spylls (Hunspell) |
| `Frontend/` | React 19, TypeScript, Vite 8, Tiptap 3 |
| ШІ | Google Gemini API (опційно, безкоштовний ключ) |

Документація: [архітектура](docs/ARCHITECTURE.md) · [API](docs/API.md) ([OpenAPI](docs/openapi.yaml)) ·
[карта інтеграції фронтенду](docs/FRONTEND_API_MAPPING.md) · [оцінка аналізатора](docs/EVALUATION.md) ·
[план і статус](docs/IMPLEMENTATION_PLAN.md) · [наскрізна перевірка](docs/E2E_CHECK.md)

---

## 1. Вимоги

* **Python 3.12** (перевірено 3.12.9; Django 5.2 підтримує 3.10–3.13).
* **Node.js 20+** (перевірено 24.15, npm 11).
* **PostgreSQL 14+** (перевірено 16.2). Для швидкого локального запуску без PostgreSQL можна тимчасово використати SQLite.
* Необовʼязково: ключ **Google Gemini API** для пошуку сюжетних ляпів ШІ.

Усі команди нижче — для **Windows PowerShell**, з кореня репозиторію.

## 2. Backend

```powershell
cd Backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1          # якщо заблоковано: Set-ExecutionPolicy -Scope Process Bypass
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env           # потім відредагуйте .env
```

### 2.1. База даних PostgreSQL

Встановіть PostgreSQL (наприклад, інсталятор з postgresql.org або `winget install PostgreSQL.PostgreSQL.16`),
потім створіть користувача й базу (пароль придумайте свій і впишіть у `Backend\.env`):

```powershell
psql -U postgres -c "CREATE USER worldweaver WITH PASSWORD 'ваш-пароль';"
psql -U postgres -c "CREATE DATABASE worldweaver OWNER worldweaver;"
```

У `Backend\.env`: `DB_ENGINE=postgres`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`.

*Альтернатива з Docker (необовʼязково):* `$env:WW_DB_PASSWORD="ваш-пароль"; docker compose up -d` у корені репозиторію.

*Без PostgreSQL (лише для спроби/тестів):* у `.env` вкажіть `DB_ENGINE=sqlite`.

### 2.2. Міграції, адміністратор, запуск

```powershell
python manage.py migrate
python manage.py createsuperuser        # необовʼязково: доступ до /admin/
python manage.py runserver 127.0.0.1:8000
```

* API: <http://127.0.0.1:8000/api/v1/>
* Swagger UI: <http://127.0.0.1:8000/api/v1/docs/> (сторінка завантажує Swagger UI з CDN jsDelivr; сама схема — `/api/v1/schema/` або [docs/openapi.yaml](docs/openapi.yaml))

### 2.3. Фоновий обробник глибокого аналізу (окреме вікно)

```powershell
cd Backend; .\.venv\Scripts\Activate.ps1
python manage.py run_worker
```

Без нього завдання глибокого аналізу залишаються в стані «у черзі». Детерміновані перевірки працюють і без worker-а.

### 2.4. Демонстраційні дані (необовʼязково)

Зареєструйтеся в застосунку, потім:

```powershell
python manage.py seed_demo --email ваш@email
```

## 3. Frontend

```powershell
cd Frontend
npm install
Copy-Item .env.example .env.local      # необовʼязково; значення за замовчуванням підходять
npm run dev
```

Відкрийте <http://localhost:5173>. Vite проксує `/api` на `http://127.0.0.1:8000`, тому cookie-сесія та CSRF
працюють як same-origin. Production-збірка: `npm run build` (результат у `Frontend/dist`).

## 4. ШІ: Google Gemini — необовʼязково

1. Відкрийте <https://aistudio.google.com>, увійдіть акаунтом Google → **Get API key** → **Create API key**.
   Карта не потрібна, безкоштовний тариф має ліміти запитів.
2. Впишіть ключ у `Backend\.env`: `GEMINI_API_KEY=...` (файл у `.gitignore`, ключ не потрапить у Git).
3. Перезапустіть `runserver` і `run_worker`. Сторінка «Перевірка» покаже «ШІ готовий».

Модель за замовчуванням — `gemini-flash-lite-latest` (швидка, рідко перевантажена); розумніша й повільніша —
`GEMINI_MODEL=gemini-flash-latest`, а при перевантаженні вона автоматично замінюється на `GEMINI_FALLBACK_MODEL`.

**Приватність.** Для пошуку ляпів текст розділів, факти з енциклопедії та хронології надсилаються в Google.
На безкоштовному тарифі Google може використовувати надіслані дані для покращення своїх моделей. Ключ
передається лише в заголовку запиту й не потрапляє в логи чи браузер. Без ключа решта застосунку працює, а
перевірка ШІ завершується повідомленням про недоступність і результатами детермінованих перевірок.

## 5. Правопис (українська)

Сервіс перевірки правопису використовує Hunspell-словник **uk_UA** з репозиторію LibreOffice (MPL 1.1,
на основі проєкту dict_uk). Файли словника не зберігаються в Git:

```powershell
cd Backend\dictionaries
Invoke-WebRequest https://raw.githubusercontent.com/LibreOffice/dictionaries/master/uk_UA/uk_UA.aff -OutFile uk_UA.aff
Invoke-WebRequest https://raw.githubusercontent.com/LibreOffice/dictionaries/master/uk_UA/uk_UA.dic -OutFile uk_UA.dic
```

Без словника перевірка правопису повертає «недоступно», решта працює. Відповідність певному виданню
«Українського правопису» (зокрема 2026 року) **не заявляється**: результат такий, як словник.

## 6. Тести

```powershell
cd Backend; .\.venv\Scripts\Activate.ps1
python -m pytest                                   # використовує БД із .env (тестова БД створюється автоматично)
$env:RUN_GEMINI_TESTS="1"; python -m pytest -m gemini   # необовʼязковий тест із реальним Gemini (надсилає тестовий текст у Google)
python manage.py evaluate_consistency --markdown ..\docs\EVALUATION.md   # метрики аналізатора

cd ..\Frontend
npm run lint
npm run build                                      # tsc -b + vite build
```

Для PostgreSQL користувачу БД потрібне право `CREATEDB` (pytest створює тестову базу `test_worldweaver`):
`psql -U postgres -c "ALTER USER worldweaver CREATEDB;"`.

## 7. Типові проблеми

| Симптом | Причина / рішення |
|---|---|
| `connection refused` / `password authentication failed` при `migrate` | PostgreSQL не запущений або невірні `DB_*` у `Backend\.env`. Це не помилка коду. |
| `DJANGO_SECRET_KEY must be set` | У `.env` вимкнено `DJANGO_DEBUG`, але не задано ключ. Згенеруйте: `python -c "import secrets; print(secrets.token_urlsafe(50))"`. |
| Фронтенд показує «Немає звʼязку з сервером Worldweaver» | Не запущено `runserver` або змінено порт — перевірте `VITE_PROXY_TARGET`. |
| 403 CSRF при запитах | Відкривайте фронтенд через Vite (`localhost:5173`), не напряму з іншого origin; для іншого origin додайте його в `CSRF_TRUSTED_ORIGINS` і `CORS_ALLOWED_ORIGINS`. |
| Завдання аналізу «у черзі» без кінця | Не запущено `python manage.py run_worker`. |
| «ШІ недоступний: немає GEMINI_API_KEY» | Додайте ключ у `Backend\.env` і перезапустіть `runserver` та `run_worker`. |
| «Денний безкоштовний ліміт Gemini вичерпано» | Запустіть перевірку завтра — вона продовжиться з місця зупинки. |
| «Модель … недоступна для цього ключа» | Змініть `GEMINI_MODEL` у `Backend\.env` (наприклад `gemini-flash-lite-latest`). |
| `Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope Process Bypass` (лише для поточного вікна). |

## 8. Відомі обмеження

* Детерміновані текстові евристики працюють із лексичними шаблонами української мови: перифраз смерті
  («серце зупинилося назавжди») не розпізнається, імена-омоніми звичайних слів можуть давати хибні спрацьовування
  (див. випадки `hard_*` у [EVALUATION.md](docs/EVALUATION.md)). Займенники не розвʼязуються.
* Контрольний набір невеликий і складений разом із правилами — метрики не є оцінкою на реальних рукописах.
* Пошук ляпів ШІ залежить від моделі Gemini й може помилятися; кожна знахідка має перевірені цитати, але
  рішення лишається за автором. Безкоштовний тариф Gemini має ліміти запитів на хвилину й на день.
* Пошук — `icontains` (без повнотекстових індексів і векторного пошуку); для великих світів варто додати PostgreSQL FTS.
* DOCX: переносяться абзаци, заголовки, жирний/курсив/підкреслення/закреслення, прості списки; таблиці, виноски,
  колонтитули, зображення й рецензування — ні.
* Фронтенд-тестів немає (у проєкті не було тестової інфраструктури); перевірка — `tsc`, `eslint`, збірка й ручний
  наскрізний сценарій.
* Сесійна автентифікація розрахована на локальне використання; для мережевого розгортання потрібні HTTPS,
  `DJANGO_DEBUG=false`, `DJANGO_SECRET_KEY`, налаштовані `ALLOWED_HOSTS`, а також окремий сервер статичних файлів.
