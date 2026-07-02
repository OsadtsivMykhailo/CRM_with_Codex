# Multisoft CRM — alpha

Локальна CRM для IT-компанії на Django REST Framework, Vue 3 та MySQL.

## Структура

- `backend/` — Django API.
- `frontend/` — Vue 3 + Vite.
- `PROJECT_REQUIREMENTS.md` — погоджені вимоги.
- `AGENTS.md` — правила роботи над проєктом.

## Швидкий запуск alpha без установленого MySQL

SQLite використовується тут лише як тимчасовий локальний режим демонстрації. Цільова база проєкту — MySQL.

У першому PowerShell-терміналі з кореня проєкту:

```powershell
$env:CRM_USE_SQLITE='1'
.\.venv\Scripts\python.exe backend\manage.py migrate
.\.venv\Scripts\python.exe backend\manage.py create_alpha_admin --password 'AlphaAdmin123!'
.\.venv\Scripts\python.exe backend\manage.py runserver 127.0.0.1:8000
```

У другому PowerShell-терміналі:

```powershell
$env:Path = 'C:\Users\Admins\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin;' + $env:Path
Set-Location frontend
& .\node_modules\.bin\vite.cmd --host 127.0.0.1
```

Відкрийте `http://127.0.0.1:5173` і увійдіть як `admin` / `AlphaAdmin123!`. Цей пароль призначений лише для локальної альфи.

## Запуск однією задачею у VS Code

Перед першим запуском встановіть Python-залежності та локальний Mailpit:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-mailpit.ps1
$env:CRM_USE_SQLITE='1'
.\.venv\Scripts\python.exe backend\manage.py migrate
```

1. Відкрийте кореневу папку CRM у VS Code.
2. Натисніть `Ctrl+Shift+P`.
3. Оберіть `Tasks: Run Task`.
4. Запустіть `CRM: Start Alpha`.

VS Code запустить Django, Vite, фоновий email-worker і Mailpit. Для зупинки використайте `Tasks: Terminate All Tasks`.

- CRM: `http://127.0.0.1:5173`.
- Перехоплені локальні листи Mailpit: `http://127.0.0.1:8025`.

## Email-розсилки

- Адміністратор налаштовує один SMTP-сервер, загальні адреси та спільні шаблони.
- Email працівника в його профілі використовується як особиста корпоративна адреса.
- Працівник може писати доступним клієнтам, групам клієнтів або всім доступним неархівним клієнтам.
- Одна розсилка підтримує до 100 унікальних адрес і вкладення до 10 МБ.
- Листи й шаблони підтримують `{{FirstName}}`, `{{CompanyName}}` і `{{Company}}`; перед відправкою CRM перевіряє, чи можна заповнити кожну використану змінну для кожного одержувача.
- Рекламні листи отримують лише клієнти, які надали згоду; відписка доступна в кабінеті та за посиланням.
- Для локальної альфи SMTP вказує на Mailpit (`127.0.0.1:1025`) і не надсилає листи в інтернет.
- Для реальної пошти адміністратор зможе замінити параметри на Mailjet, Brevo або інший SMTP-сумісний сервіс.

SMTP-пароль або API-ключ зберігається зашифрованим. Для середовища поза локальною альфою обов’язково встановіть `CRM_CREDENTIAL_ENCRYPTION_KEY` з `.env.example` і не змінюйте його після збереження SMTP-секрету.

## Підготовка backend з MySQL

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Створіть базу й користувача MySQL відповідно до `.env`, потім задайте змінні середовища та виконайте:

```powershell
cd backend
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Для адміністратора можна використати команду `create_alpha_admin`, передавши власний надійний пароль.

## Запуск frontend

В окремому терміналі:

```powershell
cd frontend
pnpm install
pnpm dev
```

Вебінтерфейс: `http://127.0.0.1:5173`. API: `http://127.0.0.1:8000/api/`.
