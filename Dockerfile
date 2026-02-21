FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 8000
ENV PORT=8000

# Run both poller + dashboard (poller in background thread, dashboard as main)
CMD ["python", "run.py"]
