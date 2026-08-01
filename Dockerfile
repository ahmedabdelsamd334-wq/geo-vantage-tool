# نستخدم Python 3.9 لأنها مدعومة بشكل أفضل مع Fiona و GDAL
FROM python:3.9-slim

# نثبت GDAL من نظام التشغيل
RUN apt-get update && apt-get install -y \
    gdal-bin \
    libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

# نحدد مسارات GDAL عشان pip يعرف مكانها
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal

WORKDIR /app

# ننسخ ملف المكتبات أولاً
COPY requirements.txt .

# نثبت المكتبات (الآن fiona مش هيحاول يبني نفسه من الصفر)
RUN pip install --no-cache-dir -r requirements.txt

# ننسخ باقي الملفات
COPY . .

# أمر التشغيل
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8080"]
