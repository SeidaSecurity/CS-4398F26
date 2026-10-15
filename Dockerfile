FROM python:3.11-slim

WORKDIR /srv/app
COPY pyproject.toml README ./
COPY app ./app
RUN pip install --no-cache-dir .

EXPOSE 8000/tcp 514/udp 514/tcp
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
