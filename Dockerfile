# escape=`
FROM python:3.12-windowsservercore-ltsc2022

ENV PYTHONDONTWRITEBYTECODE=1 `
    PYTHONUNBUFFERED=1 `
    PYTHONPATH=C:\app\src

WORKDIR C:\app

COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade pip && `
    python -m pip install --no-cache-dir -r requirements.txt

COPY src .\src

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 `
    CMD python -c "import json, urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)); assert data['status'] == 'ok'"

CMD ["python", "-m", "uvicorn", "market_profile_bot.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
