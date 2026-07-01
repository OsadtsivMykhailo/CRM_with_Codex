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

1. Відкрийте кореневу папку CRM у VS Code.
2. Натисніть `Ctrl+Shift+P`.
3. Оберіть `Tasks: Run Task`.
4. Запустіть `CRM: Start Alpha`.

VS Code відкриє окремі термінали для Django та Vite. Для зупинки використайте `Tasks: Terminate Task`.

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
