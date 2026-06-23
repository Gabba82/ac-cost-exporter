FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ac_cost_exporter.py .

ENV EXPORTER_PORT=9212
ENV CONFIG_FILE=/config/schedule.json
ENV BONO_SOCIAL_PCT=0

EXPOSE 9212

CMD ["python", "-u", "ac_cost_exporter.py"]
