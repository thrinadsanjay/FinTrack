FROM python:3.10.19-alpine 

WORKDIR /fintracker

COPY requirements.txt /fintracker

RUN pip install --no-cache-dir -r /fintracker/requirements.txt --trusted-host files.pythonhosted.org --trusted-host pypi.org

EXPOSE 8000
