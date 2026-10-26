FROM python:3.11-slim

WORKDIR /app

# 先装依赖以利用 Docker 层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://mirrors.aliyun.com/pypi/simple/

COPY . .

# 默认跑演示；生产调度：CMD ["python", "main.py"]
CMD ["python", "run_demo.py"]
