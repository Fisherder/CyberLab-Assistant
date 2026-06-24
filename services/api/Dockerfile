FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir alembic==1.14.0 boto3==1.35.90 fastapi==0.115.6 cryptography==43.0.3 pydantic==2.10.4 sqlalchemy==2.0.36 uvicorn==0.34.0 PyJWT==2.10.1 "psycopg[binary]==3.2.3" python-multipart==0.0.20 pyyaml==6.0.2
COPY alembic.ini /app/alembic.ini
COPY alembic /app/alembic
COPY src /app/src
ENV PYTHONPATH=/app/src
USER 65532:65532
EXPOSE 8000
CMD ["uvicorn", "cla.main:app", "--host", "0.0.0.0", "--port", "8000"]
