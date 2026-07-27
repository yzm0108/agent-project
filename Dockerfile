# ============================================================
# Dockerfile — 把 AI Agent 项目打包成镜像
# 每条指令都是一层"蛋糕"：下面的层不变 → 上面的层有缓存 → 构建更快
# ============================================================

# ① FROM：以官方 Python 镜像为基础（像继承一个类）
FROM python:3.12-slim

# ② WORKDIR：设定容器里的工作目录（没有就自动创建）
WORKDIR /app

# ③ COPY requirements + pip install（这两步放一起，利用 Docker 缓存）
#    先只拷 requirements.txt：只要依赖不变，这层就有缓存，不用重装
COPY requirements.txt .
RUN pip install -r requirements.txt -q

# ④ COPY . ：把剩余的所有代码拷进去
COPY . .

# ⑤ ENV：设置环境变量（Python 输出不要缓冲，否则 docker logs 看不到）
ENV PYTHONUNBUFFERED=1

# ⑥ 告诉 Docker：这个容器会用到内部端口（Streamlit 默认 8501）
EXPOSE 8501

# ⑦ CMD：容器启动时默认执行的命令（可以 docker run 时覆盖）
CMD ["python", "11_agentic_rag.py"]
