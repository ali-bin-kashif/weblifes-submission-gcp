FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

# PORT is injected by both Render and Cloud Run; default to 8080 locally
CMD chainlit run app.py --host 0.0.0.0 --port ${PORT:-8080}