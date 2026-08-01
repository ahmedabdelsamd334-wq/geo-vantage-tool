# نستخدم صورة Python الرسمية (موجودة دايماً ومضمونة)
FROM python:3.10-slim

# نثبت مكتبات نظام التشغيل اللي محتاجها GDAL
RUN apt-get update && apt-get install -y \
    gdal-bin \
    libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

# نقول للنظام إن مكتبات GDAL موجودة فين
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal

# نحدد مجلد العمل جوه الحاوية
WORKDIR /app

# ننسخ ملف المكتبات الأول عشان نستفيد بالـ Cache
COPY requirements.txt .

# نثبت مكتبات بايثون (الـ GDAL مش هيتبنى من الصفر)
RUN pip install --no-cache-dir -r requirements.txt

# ننسخ باقي ملفات المشروع
COPY . .

# أمر التشغيل
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8080"]
