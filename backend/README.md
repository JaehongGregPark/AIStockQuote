# AIStockQuote Django Backend

IntegratedHub에서 분리한 최신 Stock 서비스입니다. 기존 호환성을 위해 `/stock/` 경로를 유지합니다.

```powershell
cd C:\Users\USER\Documents\AIStockQuote\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

접속 주소는 `http://127.0.0.1:8000/stock/`입니다. 관리자 기능은 이 프로젝트의 Django 관리자 계정을 사용합니다.
