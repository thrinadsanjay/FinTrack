FROM python:3.10.19-alpine 

WORKDIR /app

COPY requirements.txt /app

RUN pip install --no-cache-dir -r /app/requirements.txt --trusted-host files.pythonhosted.org --trusted-host pypi.org

EXPOSE 8000