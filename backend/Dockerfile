FROM python:3.12-slim

WORKDIR /app

# 国内 pip / uv 镜像源
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn \
    UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple

# debian 12 (python:3.12-slim 基础) 的 apt 源切阿里云(可选,加速容器内 apt)
RUN sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g; \
            s|http://security.debian.org|https://mirrors.aliyun.com|g' \
    /etc/apt/sources.list.d/debian.sources 2>/dev/null || true

# 不走 GHCR 拉 uv,直接 pip 装
RUN pip install --no-cache-dir uv

COPY pyproject.toml .
RUN uv pip install --system -r pyproject.toml

COPY . .

# 生产模式:不带 --reload
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
