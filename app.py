
import os
import sqlite3
import requests
import datetime
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify, Response
from werkzeug.utils import secure_filename

# --- 設定 ---
DB_NAME = "farm_v2.db"
UPLOAD_FOLDER = 'uploads'
CSV_PATH = "新庄麦筆リスト.xlsx"

MAP_URLS = {
    "NDVI": "https://kitsukisaiseikyo-byte.github.io/mugimap-shinjo2026/index.html",
    "NDWI": "https://kitsukisaiseikyo-byte.github.io/mugimap-shinjo2026/ndwi.html",
    "GNDVI": "https://kitsukisaiseikyo-byte.github.io/mugimap-shinjo2026/gndvi.html"
}
LAT = 33.416
LON = 131.621

# --- ディレクトリ設定 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_PATH = os.path.join(BASE_DIR, UPLOAD_FOLDER)
if not os.path.exists(UPLOAD_PATH):
    os.makedirs(UPLOAD_PATH)

# --- エクセル読み込み ---
try:
    df = pd.read_excel(os.path.join(BASE_DIR, CSV_PATH))
    FIELD_LIST = sorted(df['address'].unique().tolist())
except Exception as e:
    print(f"Excel load error: {e}")
    FIELD_LIST = ["読み込み失敗"]

# --- DB初期化 ---
def init_db():
    conn = sqlite3.connect(os.path.join(BASE_DIR, DB_NAME))
    cur = conn.cursor()
    cur.execute('CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, field_name TEXT NOT NULL, activity TEXT NOT NULL, worker TEXT NOT NULL, image_path TEXT)')
    cur.execute('CREATE TABLE IF NOT EXISTS schedules (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT, color TEXT)')
    conn.commit()
    conn.close()

init_db()

# --- 天気取得 ---
def get_weather():
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}&daily=weathercode,temperature_2m_max,temperature_2m_min&timezone=Asia%2FTokyo&forecast_days=3"
        res = requests.get(url, timeout=2)
        data = res.json()
        daily = data.get('daily', {})
        forecasts = []
        wmo_map = {0: '☀️', 1: '🌤️', 2: '⛅', 3: '☁️', 45: '🌫️', 48: '🌫️', 51: '🌦️', 53: '🌦️', 55: '🌧️', 61: '☔', 80: '🌦️', 95: '⛈️'}
        for i in range(3):
            code = daily['weathercode'][i]
            forecasts.append({'date': daily['time'][i], 'max_temp': daily['temperature_2m_max'][i], 'min_temp': daily['temperature_2m_min'][i], 'emoji': wmo_map.get(code, '☔')})
        return forecasts
    except:
        return []

# --- アプリ本体 ---
app = Flask(__name__)

@app.context_processor
def inject_weather(): return dict(weather=get_weather())

@app.route('/')
def index():
    map_type = request.args.get('map_type', 'NDVI')
    if map_type not in MAP_URLS: map_type = 'NDVI'
    return render_template('dashboard.html', page='map', current_map=map_type, default_map=MAP_URLS[map_type])

@app.route('/schedule')
def schedule(): return render_template('schedule.html', page='schedule')

@app.route('/api/events')
def api_events():
    conn = sqlite3.connect(os.path.join(BASE_DIR, DB_NAME))
    cur = conn.cursor()
    cur.execute("SELECT title, start_date FROM schedules")
    events = [{"title": r[0], "start": r[1], "color": "#3788d8"} for r in cur.fetchall()]
    conn.close()
    return jsonify(events)

@app.route('/schedule_add', methods=['POST'])
def schedule_add():
    conn = sqlite3.connect(os.path.join(BASE_DIR, DB_NAME))
    conn.execute("INSERT INTO schedules (title, start_date) VALUES (?, ?)", (request.form['title'], request.form['start_date']))
    conn.commit()
    conn.close()
    return redirect(url_for('schedule'))

@app.route('/report_list')
def report_list():
    conn = sqlite3.connect(os.path.join(BASE_DIR, DB_NAME))
    cur = conn.cursor()
    cur.execute("SELECT * FROM reports ORDER BY date DESC")
    return render_template('report_list.html', reports=cur.fetchall(), page='report')

@app.route('/export_report')
def export_report():
    conn = sqlite3.connect(os.path.join(BASE_DIR, DB_NAME))
    df = pd.read_sql_query("SELECT date, field_name, worker, activity FROM reports ORDER BY date DESC", conn)
    conn.close()
    df.columns = ['日付', '圃場', '作業者', '作業内容']
    csv_str = df.to_csv(index=False)
    # Shift-JIS強制変換
    csv_bytes = csv_str.encode('cp932', errors='ignore')
    return Response(csv_bytes, mimetype="text/csv", headers={"Content-disposition": "attachment; filename=daily_report_sjis.csv"})

@app.route('/report_add', methods=['GET', 'POST'])
def report_add():
    if request.method == 'POST':
        date = request.form['date']
        fields = request.form.getlist('field_name')
        field_str = ",".join(fields) if fields else "未選択"
        activity = request.form['activity']
        worker = request.form['worker']
        image_filename = None
        if 'image' in request.files:
            file = request.files['image']
            if file.filename != '':
                filename = secure_filename(file.filename)
                filename = f"{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
                file.save(os.path.join(UPLOAD_PATH, filename))
                image_filename = filename
        conn = sqlite3.connect(os.path.join(BASE_DIR, DB_NAME))
        conn.execute("INSERT INTO reports (date, field_name, activity, worker, image_path) VALUES (?, ?, ?, ?, ?)",
                     (date, field_str, activity, worker, image_filename))
        conn.commit()
        conn.close()
        return redirect(url_for('report_list'))
    return render_template('report_form.html', fields=FIELD_LIST, today=datetime.date.today().strftime('%Y-%m-%d'), page='report')

@app.route('/report_delete', methods=['POST'])
def report_delete():
    report_id = request.form['id']
    conn = sqlite3.connect(os.path.join(BASE_DIR, DB_NAME))
    conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('report_list'))

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_PATH, filename)

if __name__ == '__main__':
    # Renderではポート番号を環境変数から取得する
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
