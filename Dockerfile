# Para rodar no home server (ZimaOS) no futuro. Os dados ficam no volume /data.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY financas ./financas
COPY rules.yaml .
ENV FIN_DATA_DIR=/data
EXPOSE 8501
CMD ["streamlit", "run", "financas/ui/app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
