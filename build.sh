#!/bin/bash
apt-get update
apt-get install -y gdal-bin libgdal-dev
# تحسين سرعة التثبيت باستخدام cache
pip install --upgrade pip
pip install --default-timeout=100 -r requirements.txt