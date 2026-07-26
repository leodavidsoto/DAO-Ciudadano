# DAO Ciudadana — Backend API
# Imagen portable: respeta $PORT, así que sirve igual en Render, Cloud Run,
# Koyeb o Fly.io sin cambios.
#
#   docker build -t dao-api ./backend
#   docker run -p 8000:8000 \
#     -e MONGO_URL='mongodb+srv://...' \
#     -e CORS_ORIGINS='http://localhost:3000' \
#     dao-api

FROM python:3.11-slim

# No escribir .pyc y no bufferizar stdout (logs visibles en tiempo real)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

# Dependencias primero: capa cacheable, no se reinstala si solo cambia el código
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código de la aplicación
COPY . .

# Usuario sin privilegios
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,os,sys; sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",8000)}/health').status==200 else 1)"

# sh -c para que $PORT se expanda en runtime, no en build
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
