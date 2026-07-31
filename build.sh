#!/bin/bash
apt-get update
apt-get install -y gdal-bin libgdal-dev
pip install --upgrade pip
pip install -r requirements.txt