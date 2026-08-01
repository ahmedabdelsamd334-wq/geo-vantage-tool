FROM osgeo/gdal:ubuntu-full-3.6.4

# نثبت Python 3.10 لأن الصورة مش جايبة بايثون
RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# نربط python3 بـ python عشان الأوامر تشتغل
RUN ln -s /usr/bin/python3 /usr/bin/python

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .

CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8080"]
