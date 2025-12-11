
import os
import sqlite3
import requests
import datetime
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify, Response, flash
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user

# --- 設定 ---
DB_NAME = "farm_v2.db"
UPLOAD_FOLDER = 'uploads'
CSV_PATH = "新庄麦筆リスト.xlsx"
SECRET_KEY = "secret_key_change_this"

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
    FIELD_LIST = ["読み込み失敗"]

# --- アプリ本体とLoginManager ---
app = Flask(__name__)
app.secret_key = SECRET_KEY
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, username, password):
        self.id = id
        self.username = username
        self.password = password

# --- DB初期化 ---
def init_db():
    conn = sqlite3.connect(os.path.join(BASE_DIR, DB_NAME))
    cur = conn.cursor()
    cur.execute('CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, field_name TEXT NOT NULL, activity TEXT NOT NULL, worker TEXT NOT NULL, image_path TEXT)')
    cur.execute('CREATE TABLE IF NOT EXISTS schedules (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT, color TEXT)')
    cur.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL)')
    
    cur.execute('SELECT count(*) FROM users')
    if cur.fetchone()[0] == 0:
        default_pass = generate_password_hash('password')
        cur.execute('INSERT INTO users (username, password) VALUES (?, ?)', ('admin', default_pass))
    
    conn.commit()
    conn.close()

init_db()

@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect(os.path.join(BASE_DIR, DB_NAME))
    cur = conn.cursor()
    cur.execute("SELECT id, username, password FROM users WHERE id = ?", (user_id,))
    res = cur.fetchone()
    conn.close()
    if res:
        return User(id=res[0], username=res[1], password=res[2])
    return None

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

@app.context_processor
def inject_weather(): return dict(weather=get_weather())

# --- ルーティング ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = sqlite3.connect(os.path.join(BASE_DIR, DB_NAME))
        cur = conn.cursor()
        cur.execute("SELECT id, username, password FROM users WHERE username = ?", (username,))
        user_data = cur.fetchone()
        conn.close()
        if user_data and check_password_hash(user_data[2], password):
            user = User(id=user_data[0], username=user_data[1], password=user_data[2])
            login_user(user)
            return redirect(url_for('index'))
        else:
            flash('ユーザー名またはパスワードが違います')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    map_type = request.args.get('map_type', 'NDVI')
    if map_type not in MAP_URLS: map_type = 'NDVI'
    return render_template('dashboard.html', page='map', current_map=map_type, default_map=MAP_URLS[map_type])

# --- スケジュール関連 ---
@app.route('/schedule')
@login_required
def schedule(): return render_template('schedule.html', page='schedule')

@app.route('/api/events')
@login_required
def api_events():
    conn = sqlite3.connect(os.path.join(BASE_DIR, DB_NAME))
    cur = conn.cursor()
    cur.execute("SELECT id, title, start_date FROM schedules")
    events = [{"id": r[0], "title": r[1], "start": r[2], "color": "#3788d8"} for r in cur.fetchall()]
    conn.close()
    return jsonify(events)

@app.route('/schedule_add', methods=['POST'])
@login_required
def schedule_add():
    conn = sqlite3.connect(os.path.join(BASE_DIR, DB_NAME))
    conn.execute("INSERT INTO schedules (title, start_date) VALUES (?, ?)", (request.form['title'], request.form['start_date']))
    conn.commit()
    conn.close()
    return redirect(url_for('schedule'))

@app.route('/schedule_update', methods=['POST'])
@login_required
def schedule_update():
    event_id = request.form['id']
    title = request.form['title']
    conn = sqlite3.connect(os.path.join(BASE_DIR, DB_NAME))
    conn.execute("UPDATE schedules SET title = ? WHERE id = ?", (title, event_id))
    conn.commit()
    conn.close()
    return redirect(url_for('schedule'))

@app.route('/schedule_delete', methods=['POST'])
@login_required
def schedule_delete():
    event_id = request.form['id']
    conn = sqlite3.connect(os.path.join(BASE_DIR, DB_NAME))
    conn.execute("DELETE FROM schedules WHERE id = ?", (event_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('schedule'))

# --- 日報関連 ---
@app.route('/report_list')
@login_required
def report_list():
    conn = sqlite3.connect(os.path.join(BASE_DIR, DB_NAME))
    cur = conn.cursor()
    cur.execute("SELECT * FROM reports ORDER BY date DESC")
    return render_template('report_list.html', reports=cur.fetchall(), page='report')

@app.route('/export_report')
@login_required
def export_report():
    conn = sqlite3.connect(os.path.join(BASE_DIR, DB_NAME))
    df = pd.read_sql_query("SELECT date, field_name, worker, activity FROM reports ORDER BY date DESC", conn)
    conn.close()
    df.columns = ['日付', '圃場', '作業者', '作業内容']
    csv_str = df.to_csv(index=False)
    csv_bytes = csv_str.encode('cp932', errors='ignore')
    return Response(csv_bytes, mimetype="text/csv", headers={"Content-disposition": "attachment; filename=daily_report_sjis.csv"})

@app.route('/report_add', methods=['GET', 'POST'])
@login_required
def report_add():
    edit_id = request.args.get('edit_id')
    edit_data = None
    
    if edit_id:
        conn = sqlite3.connect(os.path.join(BASE_DIR, DB_NAME))
        cur = conn.cursor()
        cur.execute("SELECT * FROM reports WHERE id = ?", (edit_id,))
        edit_data = cur.fetchone()
        conn.close()

    if request.method == 'POST':
        report_id = request.form.get('id')
        date = request.form['date']
        fields = request.form.getlist('field_name')
        field_str = ",".join(fields) if fields else "未選択"
        activity = request.form['activity']
        worker = request.form['worker']
        
        image_filename = request.form.get('existing_image')
        if 'image' in request.files:
            file = request.files['image']
            if file.filename != '':
                filename = secure_filename(file.filename)
                filename = f"{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
                file.save(os.path.join(UPLOAD_PATH, filename))
                image_filename = filename
        
        conn = sqlite3.connect(os.path.join(BASE_DIR, DB_NAME))
        if report_id:
            conn.execute("UPDATE reports SET date=?, field_name=?, activity=?, worker=?, image_path=? WHERE id=?",
                         (date, field_str, activity, worker, image_filename, report_id))
        else:
            conn.execute("INSERT INTO reports (date, field_name, activity, worker, image_path) VALUES (?, ?, ?, ?, ?)",
                         (date, field_str, activity, worker, image_filename))
        conn.commit()
        conn.close()
        return redirect(url_for('report_list'))
    
    today = datetime.date.today().strftime('%Y-%m-%d')
    selected_fields = []
    if edit_data:
        selected_fields = edit_data[2].split(',')

    return render_template('report_form.html', fields=FIELD_LIST, today=today, page='report', edit_data=edit_data, selected_fields=selected_fields)

@app.route('/report_delete', methods=['POST'])
@login_required
def report_delete():
    report_id = request.form['id']
    conn = sqlite3.connect(os.path.join(BASE_DIR, DB_NAME))
    conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('report_list'))

@app.route('/uploads/<filename>')
@login_required
def uploaded_file(filename):
    return send_from_directory(UPLOAD_PATH, filename)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
