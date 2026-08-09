import os
import re
import json
from datetime import datetime
import requests
from flask import render_template
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy


app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.makedirs(os.path.join(BASE_DIR, 'instance'), exist_ok=True)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'notes.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

@app.route('/')
def index():
    return render_template('index.html')

# Модель данных
class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    author = db.Column(db.String(100), default='Аноним')
    font_color = db.Column(db.String(20), default='#000000')
    font_size = db.Column(db.Integer, default=16)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    ip = db.Column(db.String(45))
    port = db.Column(db.String(10))
    geo_country = db.Column(db.String(100))
    geo_city = db.Column(db.String(100))
    geo_isp = db.Column(db.String(200))
    geo_as = db.Column(db.String(200))
    is_vpn = db.Column(db.Boolean)
    browser = db.Column(db.String(50))
    browser_version = db.Column(db.String(50))
    os = db.Column(db.String(50))
    os_version = db.Column(db.String(50))
    device_type = db.Column(db.String(20))
    engine = db.Column(db.String(20))
    referer = db.Column(db.Text)
    origin = db.Column(db.Text)
    screen_res = db.Column(db.String(30))
    color_depth = db.Column(db.Integer)
    pixel_ratio = db.Column(db.Float)
    window_size = db.Column(db.String(30))
    cpu_cores = db.Column(db.Integer)
    ram_gb = db.Column(db.Float)
    gpu = db.Column(db.String(200))
    network_type = db.Column(db.String(20))
    downlink = db.Column(db.Float)
    rtt = db.Column(db.Integer)
    battery_level = db.Column(db.Float)
    battery_charging = db.Column(db.Boolean)
    accounts = db.Column(db.Text)

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'content': self.content,
            'author': self.author,
            'font_color': self.font_color,
            'font_size': self.font_size,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'ip': self.ip,
            'port': self.port,
            'geo_country': self.geo_country,
            'geo_city': self.geo_city,
            'geo_isp': self.geo_isp,
            'geo_as': self.geo_as,
            'is_vpn': self.is_vpn,
            'browser': self.browser,
            'browser_version': self.browser_version,
            'os': self.os,
            'os_version': self.os_version,
            'device_type': self.device_type,
            'engine': self.engine,
            'referer': self.referer,
            'origin': self.origin,
            'screen_res': self.screen_res,
            'color_depth': self.color_depth,
            'pixel_ratio': self.pixel_ratio,
            'window_size': self.window_size,
            'cpu_cores': self.cpu_cores,
            'ram_gb': self.ram_gb,
            'gpu': self.gpu,
            'network_type': self.network_type,
            'downlink': self.downlink,
            'rtt': self.rtt,
            'battery_level': self.battery_level,
            'battery_charging': self.battery_charging,
            'accounts': self.accounts
        }

# Создаём таблицы и добавляем недостающие колонки (миграция для старых БД)
NEW_COLUMNS = [
    ('created_at', 'DATETIME'),
    ('author', "VARCHAR(100) DEFAULT 'Аноним'"),
    ('font_color', "VARCHAR(20) DEFAULT '#000000'"),
    ('font_size', 'INTEGER DEFAULT 16'),
    ('ip', 'VARCHAR(45)'),
    ('port', 'VARCHAR(10)'),
    ('geo_country', 'VARCHAR(100)'),
    ('geo_city', 'VARCHAR(100)'),
    ('geo_isp', 'VARCHAR(200)'),
    ('geo_as', 'VARCHAR(200)'),
    ('is_vpn', 'BOOLEAN'),
    ('browser', 'VARCHAR(50)'),
    ('browser_version', 'VARCHAR(50)'),
    ('os', 'VARCHAR(50)'),
    ('os_version', 'VARCHAR(50)'),
    ('device_type', 'VARCHAR(20)'),
    ('engine', 'VARCHAR(20)'),
    ('referer', 'TEXT'),
    ('origin', 'TEXT'),
    ('screen_res', 'VARCHAR(30)'),
    ('color_depth', 'INTEGER'),
    ('pixel_ratio', 'FLOAT'),
    ('window_size', 'VARCHAR(30)'),
    ('cpu_cores', 'INTEGER'),
    ('ram_gb', 'FLOAT'),
    ('gpu', 'VARCHAR(200)'),
    ('network_type', 'VARCHAR(20)'),
    ('downlink', 'FLOAT'),
    ('rtt', 'INTEGER'),
    ('battery_level', 'FLOAT'),
    ('battery_charging', 'BOOLEAN'),
    ('accounts', 'TEXT'),
]

with app.app_context():
    db.create_all()
    from sqlalchemy import text
    cols = [row[1] for row in db.session.execute(text("PRAGMA table_info(note)")).fetchall()]
    added = []
    for col, ctype in NEW_COLUMNS:
        if col not in cols:
            db.session.execute(text(f"ALTER TABLE note ADD COLUMN {col} {ctype}"))
            added.append(col)
    if 'created_at' in added:
        Note.query.update({Note.created_at: datetime.utcnow()})
    if 'author' in added:
        Note.query.update({Note.author: 'Аноним', Note.font_color: '#000000', Note.font_size: 16})
    db.session.commit()
    
    

# Парсим User-Agent (без внешних зависимостей)
def parse_user_agent(ua):
    ua = ua or ''
    result = {
        'browser': 'Unknown',
        'browser_version': None,
        'os': 'Unknown',
        'os_version': None,
        'device_type': 'desktop',
        'engine': 'Unknown',
    }
    if 'Mobi' in ua:
        result['device_type'] = 'mobile'
    elif 'Tablet' in ua or 'iPad' in ua:
        result['device_type'] = 'tablet'

    if 'Windows' in ua:
        result['os'] = 'Windows'
        m = re.search(r'Windows NT (\d+\.?\d*)', ua)
        if m:
            result['os_version'] = m.group(1)
    elif 'Android' in ua:
        result['os'] = 'Android'
        m = re.search(r'Android (\d+\.?\d*)', ua)
        if m:
            result['os_version'] = m.group(1)
    elif 'iPhone' in ua or 'iPad' in ua:
        result['os'] = 'iOS'
        m = re.search(r'iPhone OS (\d+[_\d]*)', ua)
        if m:
            result['os_version'] = m.group(1).replace('_', '.')
    elif 'Mac OS X' in ua or 'Macintosh' in ua:
        result['os'] = 'macOS'
        m = re.search(r'Mac OS X (\d+[_\d.]*)', ua)
        if m:
            result['os_version'] = m.group(1).replace('_', '.')
    elif 'CrOS' in ua:
        result['os'] = 'ChromeOS'
    elif 'Linux' in ua:
        result['os'] = 'Linux'

    if 'Edg/' in ua:
        result['browser'] = 'Edge'
        result['engine'] = 'Blink'
        m = re.search(r'Edg/(\d+)', ua)
        if m:
            result['browser_version'] = m.group(1)
    elif 'OPR/' in ua:
        result['browser'] = 'Opera'
        result['engine'] = 'Blink'
        m = re.search(r'OPR/(\d+)', ua)
        if m:
            result['browser_version'] = m.group(1)
    elif 'Firefox/' in ua:
        result['browser'] = 'Firefox'
        result['engine'] = 'Gecko'
        m = re.search(r'Firefox/(\d+)', ua)
        if m:
            result['browser_version'] = m.group(1)
    elif 'Chrome/' in ua:
        result['browser'] = 'Chrome'
        result['engine'] = 'Blink'
        m = re.search(r'Chrome/(\d+)', ua)
        if m:
            result['browser_version'] = m.group(1)
    elif 'Safari/' in ua:
        result['browser'] = 'Safari'
        result['engine'] = 'WebKit'
        m = re.search(r'Version/(\d+)', ua)
        if m:
            result['browser_version'] = m.group(1)
    elif 'Trident/' in ua or 'MSIE' in ua:
        result['browser'] = 'IE'
        result['engine'] = 'Trident'
    return result

# Геолокация по IP через бесплатный ip-api.com
def geo_by_ip(ip):
    if not ip or ip.startswith(('127.', '10.', '192.168.', '172.16.', '::1', '::ffff:127')):
        return None
    try:
        r = requests.get(
            f'http://ip-api.com/json/{ip}',
            params={'fields': 'status,country,city,isp,as,proxy,hosting'},
            timeout=3
        )
        d = r.json()
        if d.get('status') == 'success':
            return d
    except Exception:
        pass
    return None

# Эвристика: похоже ли на VPN/прокси/хостинг по названию провайдера и AS
VPN_KEYWORDS = ['hosting', 'cloud', 'datacenter', 'data center', 'vpn', 'proxy',
                'digitalocean', 'ovh', 'amazon', 'aws', 'google cloud', 'azure',
                'hetzner', 'linode', 'vultr', 'leaseweb', 'server']

def detect_vpn(isp, as_):
    haystack = f'{isp or ""} {as_ or ""}'.lower()
    return any(k in haystack for k in VPN_KEYWORDS)

# Эндпоинт: получить все заметки
@app.route('/notes', methods=['GET'])
def get_notes():
    notes = Note.query.order_by(Note.created_at.desc(), Note.id.desc()).all()
    return jsonify([n.to_dict() for n in notes])

# Эндпоинт: создать заметку
@app.route('/notes', methods=['POST'])
def create_note():
    data = request.get_json()
    ip = request.remote_addr
    port = request.environ.get('REMOTE_PORT')
    ua = parse_user_agent(request.headers.get('User-Agent'))
    geo = geo_by_ip(ip) or {}
    new_note = Note(
        title=data['title'],
        content=data['content'],
        author=data.get('author') or 'Аноним',
        font_color=data.get('font_color') or '#000000',
        font_size=data.get('font_size') or 16,
        ip=ip,
        port=str(port) if port else None,
        geo_country=geo.get('country'),
        geo_city=geo.get('city'),
        geo_isp=geo.get('isp'),
        geo_as=geo.get('as'),
        is_vpn=detect_vpn(geo.get('isp'), geo.get('as')),
        browser=ua['browser'],
        browser_version=ua['browser_version'],
        os=ua['os'],
        os_version=ua['os_version'],
        device_type=ua['device_type'],
        engine=ua['engine'],
        referer=request.referrer,
        origin=request.headers.get('Origin'),
        screen_res=data.get('screen_res'),
        color_depth=data.get('color_depth'),
        pixel_ratio=data.get('pixel_ratio'),
        window_size=data.get('window_size'),
        cpu_cores=data.get('cpu_cores'),
        ram_gb=data.get('ram_gb'),
        gpu=data.get('gpu'),
        network_type=data.get('network_type'),
        downlink=data.get('downlink'),
        rtt=data.get('rtt'),
        battery_level=data.get('battery_level'),
        battery_charging=data.get('battery_charging'),
        accounts=json.dumps(data.get('accounts'), ensure_ascii=False) if data.get('accounts') else None,
    )
    db.session.add(new_note)
    db.session.commit()
    return jsonify(new_note.to_dict()), 201

# Эндпоинт: удалить заметку по id
@app.route('/notes/<int:id>', methods=['DELETE'])
def delete_note(id):
    note = Note.query.get_or_404(id)
    db.session.delete(note)
    db.session.commit()
    return '', 204

if __name__ == '__main__':
    app.run(debug=True)
