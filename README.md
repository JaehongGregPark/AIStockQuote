# AIStockQuote

AI 기반 주식 시세·회원·운영 기능을 제공하는 독립 Django 애플리케이션입니다. 프로젝트 루트가 애플리케이션의 실행 기준이며, 별도의 `backend/` 진입점은 사용하지 않습니다.

## 프로젝트 구조

- `manage.py`: Django 관리 명령 진입점
- `config/`: Django 프로젝트 설정, URL, WSGI/ASGI
- `apps/`: 주식 시세, AI 분석, 회원, 약관, 알림, 뉴스 및 관리자 기능
- `tests/`: Django 독립 실행 검증 테스트
- `legacy_fastapi/`: 이전 FastAPI 구현과 테스트(이력 보존용)
- `docs/`: 구축 현황과 운영 가이드

## 설치 및 실행

```powershell
cd C:\Users\USER\Documents\AIStockQuote
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

브라우저에서 `http://127.0.0.1:8000/`에 접속하면 `/stock/`으로 이동합니다. 관리자 화면은 `/admin/`입니다.

## 테스트

```powershell
pytest
```

## 배포

Docker 이미지는 루트의 Django 프로젝트를 실행합니다.

```powershell
docker build -t aistockquote .
docker run --env-file .env -p 8000:8000 aistockquote
```

운영 환경에서는 `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, 데이터베이스 및 메일 환경변수를 반드시 설정하세요. PostgreSQL 연결값이 없으면 루트의 `db.sqlite3`를 사용합니다.
