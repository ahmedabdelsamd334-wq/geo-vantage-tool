import os
import zipfile
import tempfile
import shutil
import json
import base64
from io import BytesIO
from flask import (
    Flask,
    request,
    render_template,
    send_file,
    jsonify,
    session,
    flash,
    redirect,
    url_for,
    get_flashed_messages
)
import ezdxf
from shapely.geometry import Polygon, Point, LineString, MultiLineString
import geopandas as gpd
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MPLPolygon
from datetime import datetime
import folium
import branca.colormap as cm
import uuid
from math import cos, sin, radians
import re
import pickle

# محاولة استيراد GDAL لقراءة DWG (اختياري)
try:
    from osgeo import ogr
    GDAL_AVAILABLE = True
except ImportError:
    GDAL_AVAILABLE = False
    print("GDAL not installed. DWG files will not be supported.")

app = Flask(__name__)
app.secret_key = 'geo-vantage-secret-key-2025'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['OUTPUT_FOLDER'] = 'outputs'
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # 200 MB
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_TYPE'] = 'filesystem'

for folder in [app.config['UPLOAD_FOLDER'], app.config['OUTPUT_FOLDER']]:
    os.makedirs(folder, exist_ok=True)

# إنشاء مجلد downloads لتخزين الملفات النهائية
download_dir = os.path.join(app.root_path, 'downloads')
os.makedirs(download_dir, exist_ok=True)

# ---- دوال قراءة الطبقات ----
def get_layers_from_dxf(dxf_path):
    try:
        doc = ezdxf.readfile(dxf_path)
        layers = set()
        for entity in doc.modelspace():
            layers.add(entity.dxf.layer)
        for block in doc.blocks:
            for entity in block:
                layers.add(entity.dxf.layer)
        return sorted(layers)
    except Exception as e:
        print(f"Error reading DXF layers: {e}")
        return []

def get_layers_from_dwg(dwg_path):
    if not GDAL_AVAILABLE:
        return []
    try:
        driver = ogr.GetDriverByName('DWG')
        ds = driver.Open(dwg_path, 0)
        if ds is None:
            return []
        layers = set()
        for i in range(ds.GetLayerCount()):
            layer = ds.GetLayer(i)
            layers.add(layer.GetName())
        ds = None
        return sorted(layers)
    except:
        return []

def get_layers_from_file(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.dxf':
        return get_layers_from_dxf(file_path)
    elif ext == '.dwg':
        return get_layers_from_dwg(file_path)
    else:
        return []

# ---- دوال استخراج الكيانات ----
def get_xy(p):
    if hasattr(p, 'x') and hasattr(p, 'y'):
        return (p.x, p.y)
    elif isinstance(p, (list, tuple)):
        return (p[0], p[1])
    return p

def get_points(entity):
    if entity.dxftype() == 'LWPOLYLINE':
        pts = list(entity.get_points())
        return [get_xy(p) for p in pts]
    elif entity.dxftype() == 'POLYLINE':
        pts = list(entity.points())
        return [get_xy(p) for p in pts]
    elif entity.dxftype() == 'LINE':
        return [get_xy(entity.dxf.start), get_xy(entity.dxf.end)]
    else:
        return []

def extract_features_from_dxf(dxf_path):
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    features = {}
    def add_feature(layer, geom):
        if layer not in features:
            features[layer] = []
        features[layer].append(geom)
    for entity in msp:
        layer = entity.dxf.layer
        if entity.dxftype() == 'LINE':
            pts = get_points(entity)
            if len(pts) == 2:
                add_feature(layer, LineString(pts))
        elif entity.dxftype() == 'CIRCLE':
            center = entity.dxf.center
            radius = entity.dxf.radius
            pts = []
            for i in range(64):
                angle = 2 * 3.14159 * i / 64
                x = center.x + radius * cos(angle)
                y = center.y + radius * sin(angle)
                pts.append((x, y))
            add_feature(layer, Polygon(pts))
        elif entity.dxftype() == 'ARC':
            center = entity.dxf.center
            radius = entity.dxf.radius
            start_angle = radians(entity.dxf.start_angle)
            end_angle = radians(entity.dxf.end_angle)
            pts = []
            segments = 64
            for i in range(segments + 1):
                t = i / segments
                angle = start_angle + (end_angle - start_angle) * t
                x = center.x + radius * cos(angle)
                y = center.y + radius * sin(angle)
                pts.append((x, y))
            if abs(entity.dxf.start_angle - entity.dxf.end_angle) >= 359.9:
                add_feature(layer, Polygon(pts))
            else:
                add_feature(layer, LineString(pts))
        elif entity.dxftype() == 'SPLINE':
            try:
                points = list(entity.flattening(0.01))
                pts = [get_xy(p) for p in points]
                if len(pts) > 2:
                    add_feature(layer, LineString(pts))
            except:
                pass
        elif entity.dxftype() in ('LWPOLYLINE', 'POLYLINE'):
            pts = get_points(entity)
            if len(pts) > 2:
                is_closed = entity.closed or (pts[0] == pts[-1])
                if is_closed:
                    try:
                        add_feature(layer, Polygon(pts))
                    except:
                        add_feature(layer, LineString(pts))
                else:
                    add_feature(layer, LineString(pts))
        elif entity.dxftype() == 'POINT':
            p = get_xy(entity.dxf.location)
            add_feature(layer, Point(p))
        elif entity.dxftype() == 'INSERT':
            try:
                block = doc.blocks.get(entity.dxf.name)
                for e in block:
                    if e.dxftype() == 'LINE':
                        pts = get_points(e)
                        if len(pts) == 2:
                            add_feature(layer, LineString(pts))
                    elif e.dxftype() == 'CIRCLE':
                        center = e.dxf.center
                        radius = e.dxf.radius
                        pts = []
                        for i in range(64):
                            angle = 2 * 3.14159 * i / 64
                            x = center.x + radius * cos(angle)
                            y = center.y + radius * sin(angle)
                            pts.append((x, y))
                        add_feature(layer, Polygon(pts))
                    elif e.dxftype() in ('LWPOLYLINE', 'POLYLINE'):
                        pts = get_points(e)
                        if len(pts) > 2:
                            is_closed = e.closed or (pts[0] == pts[-1])
                            if is_closed:
                                try:
                                    add_feature(layer, Polygon(pts))
                                except:
                                    add_feature(layer, LineString(pts))
                            else:
                                add_feature(layer, LineString(pts))
                    elif e.dxftype() == 'POINT':
                        p = get_xy(e.dxf.location)
                        add_feature(layer, Point(p))
            except:
                pass
    return features

def extract_features_from_dwg(dwg_path):
    if not GDAL_AVAILABLE:
        return {}
    driver = ogr.GetDriverByName('DWG')
    ds = driver.Open(dwg_path, 0)
    if ds is None:
        return {}
    features = {}
    for i in range(ds.GetLayerCount()):
        layer = ds.GetLayer(i)
        layer_name = layer.GetName()
        features[layer_name] = []
        for feat in layer:
            geom = feat.GetGeometryRef()
            if geom is None:
                continue
            wkt = geom.ExportToWkt()
            from shapely import wkt as shapely_wkt
            shp_geom = shapely_wkt.loads(wkt)
            if shp_geom.geom_type == 'Polygon':
                features[layer_name].append(shp_geom)
            elif shp_geom.geom_type == 'LineString':
                features[layer_name].append(shp_geom)
            elif shp_geom.geom_type == 'Point':
                features[layer_name].append(shp_geom)
    ds = None
    return features

# ---- دوال المعالجة ----
def generate_alpha_code(n):
    result = ""
    while n >= 0:
        result = chr(ord('A') + (n % 26)) + result
        n = n // 26 - 1
        if n < 0:
            break
    return result

def process_layer(geometries, layer_type, static_data, crs):
    if not geometries:
        return None
    polygons = []
    for geom in geometries:
        if geom.geom_type == 'Polygon':
            polygons.append(geom)
        elif geom.geom_type in ('LineString', 'MultiLineString'):
            try:
                poly = Polygon(geom.coords)
                if poly.is_valid and poly.area > 0:
                    polygons.append(poly)
            except:
                pass
    if not polygons:
        return None
    gdf = gpd.GeoDataFrame(geometry=polygons, crs=crs)
    today = datetime.today().strftime('%Y-%m-%d')
    type_map = {'Land': 'أرض', 'Building': 'مبني', 'Road': 'طريق'}
    gdf['النوع'] = type_map.get(layer_type, '')
    gdf['date'] = today
    gdf['usage'] = type_map.get(layer_type, '')
    for key, val in static_data.items():
        if key in ['request_nu', 'name', 'surveyor', 'company', 'surv_num', 'gov', 'sec', 'ssec',
                   'east', 'west', 'north', 'south', 'location', 'رقم']:
            gdf[key] = val
    gdf['descriptio'] = ''
    gdf['des_build'] = ''
    gdf['Area'] = gdf.geometry.area
    gdf['رمز'] = ''
    geom_col = gdf.geometry.name
    cols = ['النوع', 'date', 'usage', 'رمز', 'request_nu', 'name', 'surveyor', 'company',
            'surv_num', 'gov', 'sec', 'ssec', 'east', 'west', 'north', 'south', 'location',
            'رقم', 'descriptio', 'des_build', 'Area', geom_col]
    gdf = gdf[cols]
    return gdf

def assign_global_codes(gdfs):
    if not gdfs:
        return gdfs
    temp_gdfs = {}
    for key, gdf in gdfs.items():
        temp = gdf.copy()
        temp['_layer_key'] = key
        temp_gdfs[key] = temp
    combined_df = pd.concat(temp_gdfs.values(), ignore_index=True)
    geom_col = 'geometry'
    for g in gdfs.values():
        if g is not None and len(g) > 0:
            geom_col = g.geometry.name
            break
    all_gdf = gpd.GeoDataFrame(combined_df, geometry=geom_col, crs=next(iter(gdfs.values())).crs)
    codes = [generate_alpha_code(i) for i in range(len(all_gdf))]
    all_gdf['رمز'] = codes
    new_gdfs = {}
    for key in gdfs.keys():
        subset = all_gdf[all_gdf['_layer_key'] == key].copy()
        subset = subset.drop(columns=['_layer_key'])
        new_gdfs[key] = subset
    return new_gdfs

def generate_main_map(project_data_list):
    if not project_data_list:
        return None
    all_gdfs = []
    all_labels = []
    for project in project_data_list:
        project_name = project.get('project_name', 'مشروع غير مسمى')
        gdfs_json = project.get('gdfs_json', {})
        crs = project.get('crs', 'EPSG:32636')
        for layer_name, gdf_json in gdfs_json.items():
            try:
                gdf = gpd.GeoDataFrame.from_features(json.loads(gdf_json))
                gdf.crs = crs
                gdf['المشروع'] = project_name
                all_gdfs.append(gdf)
                all_labels.append(f"{project_name} - {layer_name}")
            except Exception as e:
                print(f"Error reconstructing layer {layer_name}: {e}")
                continue
    if not all_gdfs:
        return None
    combined_gdf = pd.concat(all_gdfs, ignore_index=True)
    geom_col = 'geometry'
    for g in all_gdfs:
        if g is not None and len(g) > 0:
            geom_col = g.geometry.name
            break
    combined_gdf = gpd.GeoDataFrame(combined_gdf, geometry=geom_col, crs=all_gdfs[0].crs)
    try:
        combined_wgs84 = combined_gdf.to_crs(epsg=4326)
        center = combined_wgs84.geometry.centroid.iloc[0]
    except:
        center = combined_gdf.geometry.centroid.iloc[0]
    m = folium.Map(location=[center.y, center.x], zoom_start=14, tiles='OpenStreetMap', control_scale=True)
    folium.TileLayer(
        tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
        attr='Google',
        name='Google Satellite',
        overlay=False,
        control=True
    ).add_to(m)
    project_colors = {}
    color_palette = ['#1a237e', '#f57c00', '#2e7d32', '#c62828', '#6a1b9a', '#00838f', '#4e342e', '#9c27b0', '#795548']
    for i, gdf in enumerate(all_gdfs):
        if gdf is None or len(gdf) == 0:
            continue
        project_name = gdf['المشروع'].iloc[0]
        if project_name not in project_colors:
            project_colors[project_name] = color_palette[len(project_colors) % len(color_palette)]
        color = project_colors[project_name]
        try:
            gdf_wgs84 = gdf.to_crs(epsg=4326)
        except:
            gdf_wgs84 = gdf
        layer_label = all_labels[i] if i < len(all_labels) else f"طبقة {i+1}"
        tooltip_fields = ['النوع', 'رمز', 'Area', 'المشروع']
        existing_fields = [f for f in tooltip_fields if f in gdf_wgs84.columns]
        folium.GeoJson(
            gdf_wgs84.to_json(),
            name=layer_label,
            style_function=lambda x, color=color: {'fillColor': color, 'color': 'black', 'weight': 2, 'fillOpacity': 0.4},
            tooltip=folium.GeoJsonTooltip(
                fields=existing_fields,
                aliases=[f'{f}:' for f in existing_fields]
            )
        ).add_to(m)
    folium.LayerControl().add_to(m)
    return m

# ---- مسارات الموقع ----
@app.route('/', methods=['GET'])
def index():
    map_data = session.get('map_data', [])
    
    # ===== إصلاح المشاريع القديمة =====
    # إذا كان المشروع لا يحتوي على project_id، نضيفه
    # ونضمن وجود مسارات الملفات (shp_zip, excel)
    for project in map_data:
        if 'project_id' not in project:
            project['project_id'] = str(uuid.uuid4())
        # التأكد من وجود المفاتيح الأساسية
        if 'shp_zip' not in project:
            project['shp_zip'] = None
        if 'excel' not in project:
            project['excel'] = None
    session['map_data'] = map_data
    # =================================
    
    folium_map = generate_main_map(map_data)
    map_html = folium_map.get_root().render() if folium_map else None
    messages = get_flashed_messages()
    return render_template('index.html', 
                         map_html=map_html, 
                         project_count=len(map_data),
                         map_data=map_data,
                         messages=messages)

@app.route('/upload_page', methods=['GET'])
def upload_page():
    return render_template('upload.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'cad_file' not in request.files:
        flash('❌ لم يتم اختيار أي ملف', 'error')
        return redirect(url_for('upload_page'))
    file = request.files['cad_file']
    if file.filename == '':
        flash('❌ لم تختر ملفاً', 'error')
        return redirect(url_for('upload_page'))
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ['.dxf', '.dwg']:
        flash(f'❌ الامتداد {ext} غير مدعوم، يرجى اختيار DXF أو DWG', 'error')
        return redirect(url_for('upload_page'))
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size == 0:
        flash('❌ الملف فارغ (0 بايت)', 'error')
        return redirect(url_for('upload_page'))
    temp_dir = tempfile.mkdtemp()
    file_path = os.path.join(temp_dir, f"input{ext}")
    file.save(file_path)
    layers = get_layers_from_file(file_path)
    if not layers:
        flash('❌ لم يتم العثور على طبقات في الملف', 'error')
        return redirect(url_for('upload_page'))
    session['temp_file'] = file_path
    session['layers'] = layers
    flash(f'✅ تم رفع الملف "{file.filename}" بنجاح! تم اكتشاف {len(layers)} طبقة.', 'success')
    return render_template('select_layers.html', layers=layers, filename=file.filename)

@app.route('/process', methods=['POST'])
def process():
    if 'temp_file' not in session or not os.path.exists(session['temp_file']):
        flash('❌ انتهت صلاحية الملف، يرجى إعادة الرفع', 'error')
        return redirect(url_for('upload_page'))
    file_path = session['temp_file']
    ext = os.path.splitext(file_path)[1].lower()
    
    crs_input = request.form.get('crs', 'EPSG:32636')
    if crs_input in ['EPSG:32636', 'EPSG:32635']:
        crs = crs_input
    else:
        crs = 'EPSG:32636'
    
    project_name = request.form.get('project_name', '').strip()
    if not project_name:
        project_name = f"GeoVantage_{datetime.today().strftime('%Y%m%d_%H%M%S')}"
    project_name = re.sub(r'[^\w\-_]', '_', project_name)
    
    static_data = {
        'request_nu': request.form.get('request_nu', ''),
        'name': request.form.get('name', ''),
        'surveyor': request.form.get('surveyor', ''),
        'company': request.form.get('company', ''),
        'surv_num': request.form.get('surv_num', ''),
        'gov': request.form.get('gov', ''),
        'sec': request.form.get('sec', ''),
        'ssec': request.form.get('ssec', ''),
        'east': request.form.get('east', ''),
        'west': request.form.get('west', ''),
        'north': request.form.get('north', ''),
        'south': request.form.get('south', ''),
        'location': request.form.get('location', ''),
        'رقم': request.form.get('national_id', '')
    }
    
    land_layer = request.form.get('land_layer')
    building_layer = request.form.get('building_layer')
    subland_layer = request.form.get('subland_layer')
    road_layer = request.form.get('road_layer')
    points_layer = request.form.get('points_layer')

    if ext == '.dxf':
        all_features = extract_features_from_dxf(file_path)
    elif ext == '.dwg':
        all_features = extract_features_from_dwg(file_path)
    else:
        flash('❌ صيغة غير مدعومة', 'error')
        return redirect(url_for('upload_page'))

    gdfs = {}
    
    land_features = []
    if land_layer and land_layer in all_features:
        land_features.extend(all_features[land_layer])
    if subland_layer and subland_layer in all_features:
        land_features.extend(all_features[subland_layer])
    if land_features:
        gdf_land = process_layer(land_features, 'Land', static_data, crs)
        if gdf_land is not None and len(gdf_land) > 0:
            gdfs['Land'] = gdf_land

    if building_layer and building_layer in all_features:
        gdf_building = process_layer(all_features[building_layer], 'Building', static_data, crs)
        if gdf_building is not None and len(gdf_building) > 0:
            gdfs['Building'] = gdf_building

    if road_layer and road_layer in all_features:
        gdf_road = process_layer(all_features[road_layer], 'Road', static_data, crs)
        if gdf_road is not None and len(gdf_road) > 0:
            gdfs['Road'] = gdf_road

    if gdfs:
        gdfs = assign_global_codes(gdfs)

    points_gdf = None
    if points_layer and points_layer in all_features:
        point_geometries = [g for g in all_features[points_layer] if g.geom_type == 'Point']
        if point_geometries:
            points_gdf = gpd.GeoDataFrame(geometry=point_geometries, crs=crs)
            points_gdf['PointID'] = range(1, len(points_gdf) + 1)
            points_gdf['X'] = points_gdf.geometry.x
            points_gdf['Y'] = points_gdf.geometry.y

    if not gdfs and points_gdf is None:
        flash('❌ لم يتم العثور على معالم في الطبقات المختارة', 'error')
        return redirect(url_for('upload_page'))

    output_dir = tempfile.mkdtemp()
    shp_files = {}

    for key, gdf in gdfs.items():
        shp_path = os.path.join(output_dir, f"{key}.shp")
        gdf.to_file(shp_path, driver='ESRI Shapefile', encoding='utf-8')
        shp_files[key] = shp_path

    if points_gdf is not None and len(points_gdf) > 0:
        points_shp_path = os.path.join(output_dir, "Points.shp")
        points_gdf.to_file(points_shp_path, driver='ESRI Shapefile', encoding='utf-8')
        shp_files['Points'] = points_shp_path

    # ---- تحويل GeoDataFrames إلى JSON لتخزينها في الجلسة ----
    gdfs_json = {}
    for key, gdf in gdfs.items():
        gdfs_json[key] = gdf.to_json()

    # ---- إنشاء الملفات النهائية في مجلد downloads ----
    project_id = str(uuid.uuid4())
    shp_zip_filename = f"{project_name}_{project_id[:8]}_shapefiles.zip"
    shp_zip_path = os.path.join(download_dir, shp_zip_filename)
    with zipfile.ZipFile(shp_zip_path, 'w') as zipf:
        for key, shp_path in shp_files.items():
            base = os.path.splitext(shp_path)[0]
            for ext_file in ['.shp', '.shx', '.dbf', '.prj', '.cpg']:
                f = base + ext_file
                if os.path.exists(f):
                    zipf.write(f, os.path.basename(f))

    excel_path = None
    if points_gdf is not None and len(points_gdf) > 0:
        excel_filename = f"{project_name}_{project_id[:8]}_points.xlsx"
        excel_path = os.path.join(download_dir, excel_filename)
        excel_df = points_gdf[['PointID', 'X', 'Y']].copy()
        excel_df.to_excel(excel_path, index=False)

    # ---- تخزين البيانات في الجلسة ----
    map_data = session.get('map_data', [])
    project_entry = {
        'project_id': project_id,
        'project_name': project_name,
        'gdfs_json': gdfs_json,
        'crs': crs,
        'timestamp': datetime.today().strftime('%Y-%m-%d %H:%M:%S'),
        'shp_zip': shp_zip_path,
        'excel': excel_path
    }
    map_data.append(project_entry)
    session['map_data'] = map_data

    flash(f'✅ تم تحويل المشروع "{project_name}" بنجاح وإضافته إلى الخريطة!', 'success')
    return redirect(url_for('index'))

# ---- تحميل الملفات حسب المشروع ----
@app.route('/download_project/<project_id>/shp')
def download_project_shp(project_id):
    map_data = session.get('map_data', [])
    for proj in map_data:
        if proj.get('project_id') == project_id:
            shp_path = proj.get('shp_zip')
            if shp_path and os.path.exists(shp_path):
                return send_file(shp_path, as_attachment=True)
            else:
                flash('⚠️ ملف الشيب فايل غير موجود. يرجى إعادة تحويل المشروع لحفظ الملف بشكل دائم.', 'error')
                return redirect(url_for('index'))
    flash('❌ المشروع غير موجود', 'error')
    return redirect(url_for('index'))

@app.route('/download_project/<project_id>/excel')
def download_project_excel(project_id):
    map_data = session.get('map_data', [])
    for proj in map_data:
        if proj.get('project_id') == project_id:
            excel_path = proj.get('excel')
            if excel_path and os.path.exists(excel_path):
                return send_file(excel_path, as_attachment=True)
            else:
                flash('⚠️ ملف Excel غير موجود. يرجى إعادة تحويل المشروع لحفظ الملف بشكل دائم.', 'error')
                return redirect(url_for('index'))
    flash('❌ المشروع غير موجود', 'error')
    return redirect(url_for('index'))

# ---- حذف مشروع فردي ----
@app.route('/delete_project/<project_id>', methods=['POST'])
def delete_project(project_id):
    map_data = session.get('map_data', [])
    # البحث عن المشروع وحذفه
    for i, proj in enumerate(map_data):
        if proj.get('project_id') == project_id:
            # حذف الملفات من مجلد downloads (اختياري)
            shp_path = proj.get('shp_zip')
            if shp_path and os.path.exists(shp_path):
                try:
                    os.remove(shp_path)
                except:
                    pass
            excel_path = proj.get('excel')
            if excel_path and os.path.exists(excel_path):
                try:
                    os.remove(excel_path)
                except:
                    pass
            # حذف من الجلسة
            map_data.pop(i)
            session['map_data'] = map_data
            flash(f'✅ تم حذف المشروع "{proj.get("project_name", "مشروع")}" بنجاح', 'success')
            return redirect(url_for('index'))
    
    flash('❌ المشروع غير موجود', 'error')
    return redirect(url_for('index'))

@app.route('/clear_map', methods=['POST'])
def clear_map():
    # حذف جميع الملفات من مجلد downloads
    try:
        for filename in os.listdir(download_dir):
            filepath = os.path.join(download_dir, filename)
            if os.path.isfile(filepath):
                os.remove(filepath)
    except:
        pass
    session['map_data'] = []
    flash('🗑️ تم مسح جميع المشاريع من الخريطة والملفات', 'info')
    return '', 204

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)