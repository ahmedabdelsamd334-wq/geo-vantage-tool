# نستخدم Miniconda (بيئة Python مع مدير حزم متخصص)
FROM continuumio/miniconda3

# نثبت جميع المكتبات المطلوبة عبر Conda (كلها حزم جاهزة، بدون بناء)
RUN conda install -c conda-forge \
    gdal=3.6.4 \
    geopandas=0.14.3 \
    shapely=2.0.3 \
    fiona=1.9.5 \
    flask=2.3.3 \
    gunicorn \
    ezdxf \
    matplotlib=3.8.2 \
    folium=0.15.1 \
    pandas=2.1.4 \
    pyproj=3.6.1 \
    -y

# تثبيت المكتبات الصغيرة اللي مش موجودة في Conda
RUN pip install branca==0.6.0 numpy==1.26.3

# نحدد مجلد العمل
WORKDIR /app

# ننسخ الكود
COPY . .

# أمر التشغيل
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8080"]