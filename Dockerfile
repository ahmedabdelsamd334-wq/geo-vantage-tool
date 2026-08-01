# نستخدم صورة فيها Python و GDAL مثبتين مسبقاً
FROM geodata/gdal:3.6.4-python3.10

# نحدد مجلد العمل جوه الحاوية
WORKDIR /app

# ننسخ ملف المكتبات الأول عشان نستفيد بالـ Cache
COPY requirements.txt .

# نثبت المكتبات (الـ GDAL مش هيتبنى من الصفر، لأن الصورة جاهزة)
RUN pip install --no-cache-dir -r requirements.txt

# ننسخ باقي ملفات المشروع
COPY . .

# أمر التشغيل (نفس اللي في Procfile)
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8080"]