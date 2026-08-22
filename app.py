# -*- coding: utf-8 -*-
"""
============================================================================
Файл: app.py
Назначение: Бэкенд-часть приложения «Доска объявлений».

Это Flask-приложение, которое:
  1. Отдаёт клиенту HTML-страницу (templates/index.html) по адресу "/".
  2. Предоставляет REST API для работы с заметками:
       GET    /notes        — получить список всех заметок
       POST   /notes        — создать новую заметку
       DELETE /notes/<id>   — удалить заметку по id
  3. Вместе с каждой заметкой собирает и сохраняет «паспорт» посетителя
     (IP, геолокация, браузер, устройство, GPU, сеть, батарея и т.д.)
     для последующего изучения аудитории (fingerprinting).

Данные хранятся в SQLite-базе (instance/notes.db) через SQLAlchemy ORM.
============================================================================
"""

import os          # работа с путями и переменными окружения (для пути к БД)
import re          # регулярные выражения (парсинг User-Agent)
import json        # сериализация/десериализация JSON (для поля accounts)
import traceback   # формирование текста ошибки (для записи в error.log)
from datetime import datetime   # работа с датами (created_at)
import requests    # HTTP-клиент для внешних запросов (геолокация по IP)

# Импорты Flask: render_template рендерит HTML-шаблон,
# Flask — класс приложения, request — объект входящего HTTP-запроса,
# jsonify — сериализация ответа в JSON.
from flask import render_template
from flask import Flask, request, jsonify, session

# SQLAlchemy — ORM (Object-Relational Mapping): позволяет работать
# с таблицами базы данных как с Python-объектами.
from flask_sqlalchemy import SQLAlchemy

# werkzeug.security — утилиты для безопасного хранения паролей.
# generate_password_hash хэширует пароль (с солью), check_password_hash
# сверяет введённый пароль с хэшем. Открытым текстом пароли не храним.
from werkzeug.security import generate_password_hash, check_password_hash


# ---------------------------------------------------------------------------
# ИНИЦИАЛИЗАЦИЯ ПРИЛОЖЕНИЯ И НАСТРОЙКА ПОДКЛЮЧЕНИЯ К БАЗЕ ДАННЫХ
# ---------------------------------------------------------------------------

# Создаём объект Flask-приложения.
# __name__ = '__main__' при запуске напрямую, иначе — имя модуля.
# Flask использует его для поиска шаблонов и статических файлов.
app = Flask(__name__)

# BASE_DIR — абсолютный путь к папке, в которой лежит app.py.
# Это нужно, чтобы БД и папка instance создавались рядом с кодом,
# а не в текущей рабочей директории (рабочая директория может меняться).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Путь к файлу лога ошибок: лежит в корневой папке приложения (error.log),
# рядом с app.py, чтобы его легко было найти через FTP с сервера.
ERROR_LOG_PATH = os.path.join(BASE_DIR, 'error.log')


def log_error_message(msg):
    """
    Пишет сообщение/трейсбек в файл error.log (режим дополнения).

    Это отдельная функция, чтобы лог можно было писать даже тогда,
    когда приложение падает на этапе импорта — до регистрации
    Flask-обработчика ошибок (@app.errorhandler ниже).
    """
    try:
        with open(ERROR_LOG_PATH, 'a', encoding='utf-8') as f:
            f.write('\n' + '=' * 60 + '\n')          # разделитель
            f.write(datetime.utcnow().isoformat() + '\n')  # дата и время
            f.write(str(msg) + '\n')                 # текст сообщения
    except Exception:
        # Если записать лог не удалось (например, нет прав) — не падаем сами
        pass


# Создаём папку instance (Flask кладёт туда файлы, специфичные для приложения),
# если она ещё не существует. SQLAlchemy сам создаст файл БД,
# но если папки нет — создаст и её, поэтому делаем это явно заранее.
# Если создание не удалось (например, нет прав на запись) — логируем
# и прерываем запуск, чтобы ошибка не была «молчаливой».
try:
    os.makedirs(os.path.join(BASE_DIR, 'instance'), exist_ok=True)
except Exception:
    log_error_message('Ошибка создания папки instance:\n' + traceback.format_exc())
    raise

# URI подключения к базе данных: SQLite-файл notes.db в папке instance.
# sqlite:/// — протокол SQLite для файловой БД, далее идёт абсолютный путь.
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'notes.db')

# Отключаем отслеживание изменений объектов (экономим память и накладные
# расходы; эта функция почти никому не нужна в реальных проектах).
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# SECRET_KEY нужен Flask для подписи сессионных cookie (в них хранится
# id залогиненного пользователя). Берём из переменной окружения, а если
# её нет — используем fallback-значение (только для локальной разработки).
# На проде ОБЯЗАТЕЛЬНО задайте сложный SECRET_KEY через переменную среды.
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-change-me')

# Создаём объект db — мост между Flask-приложением и SQLAlchemy.
# Через него объявляются модели и выполняются запросы к БД.
db = SQLAlchemy(app)


# ---------------------------------------------------------------------------
# ЛОГИРОВАНИЕ ОШИБОК В ФАЙЛ
# ---------------------------------------------------------------------------

@app.errorhandler(Exception)
def log_unhandled_exception(error):
    """
    Глобальный обработчик необработанных исключений.

    Когда в приложении падает любое необработанное исключение
    (и сервер возвращает «Внутренняя ошибка сервера», 500),
    мы записываем полный трейсбек в файл error.log
    в корневой папке приложения.

    Это нужно для диагностики на хостинге Majordomo, где нет
    удобного просмотра логов uWSGI в панели.

    Параметры:
        error (Exception): перехваченное исключение.

    Возвращает: ответ с ошибкой 500.
    """
    # Записываем полный трейсбек через вспомогательную функцию
    log_error_message(traceback.format_exc())

    # Возвращаем стандартную ошибку 500, чтобы пользователь ничего не заметил
    return 'Внутренняя ошибка сервера', 500


# ---------------------------------------------------------------------------
# МАРШРУТ ГЛАВНОЙ СТРАНИЦЫ
# ---------------------------------------------------------------------------

# Декоратор @app.route регистрирует URL "/" как корневой адрес приложения.
@app.route('/')
def index():
    """
    Обработчик главной страницы.

    Возвращает готовый HTML, отрендеренный из шаблона templates/index.html.
    Это вся клиентская часть: формы, стили и JavaScript в одном файле.
    """
    return render_template('index.html')


# ---------------------------------------------------------------------------
# АВТОРИЗАЦИЯ ПОЛЬЗОВАТЕЛЕЙ (регистрация, вход, выход, статус)
# ---------------------------------------------------------------------------

from functools import wraps  # для декоратора login_required


def login_required(f):
    """
    Декоратор: пропускает запрос только если пользователь залогинен.

    Залогиненность определяем по наличию 'user_id' в сессии
    (подписанная cookie Flask). Если пользователь не авторизован —
    возвращаем JSON с ошибкой и кодом 401 (Unauthorized).
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Требуется авторизация'}), 401
        return f(*args, **kwargs)
    return decorated


def get_current_user():
    """Возвращает ORM-объект текущего пользователя или None."""
    if 'user_id' not in session:
        return None
    return User.query.get(session['user_id'])


@app.route('/register', methods=['POST'])
def register():
    """
    Регистрация нового пользователя.

    Ожидает JSON: {"username": "...", "password": "..."}.
    Если логин занят — возвращает ошибку 400. Иначе создаёт
    пользователя (пароль сохраняется в виде хэша) и сразу логинит.
    """
    data = request.get_json()
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''

    # Простая валидация входных данных.
    if not username or not password:
        return jsonify({'error': 'Укажите логин и пароль'}), 400
    if len(username) < 3:
        return jsonify({'error': 'Логин не короче 3 символов'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Пароль не короче 6 символов'}), 400

    # Проверяем, что такого логина ещё нет (username — уникальный).
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Логин уже занят'}), 400

    # Создаём пользователя. Пароль хэшируем — в БД попадёт только хэш.
    user = User(username=username, password_hash=generate_password_hash(password))
    db.session.add(user)
    db.session.commit()

    # Сразу «логиним» нового пользователя (кладём id в сессию).
    session['user_id'] = user.id
    return jsonify({'username': user.username}), 201


@app.route('/login', methods=['POST'])
def login():
    """
    Вход пользователя.

    Ожидает JSON: {"username": "...", "password": "..."}.
    Сверяет пароль с хэшем. При успехе кладёт user_id в сессию.
    """
    data = request.get_json()
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''

    # Ищем пользователя по логину.
    user = User.query.filter_by(username=username).first()
    # check_password_hash сверяет введённый пароль с хэшем из БД.
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({'error': 'Неверный логин или пароль'}), 401

    # Успешный вход: сохраняем id в подписанной сессии.
    session['user_id'] = user.id
    return jsonify({'username': user.username})


@app.route('/logout', methods=['POST'])
def logout():
    """Выход пользователя: очищаем сессию."""
    session.clear()
    return jsonify({'ok': True})


@app.route('/me', methods=['GET'])
def me():
    """
    Возвращает статус авторизации для клиента.

    Полезно, чтобы фронтенд понимал: показывать форму добавления
    и кнопки удаления или форму входа.
    """
    user = get_current_user()
    if user:
        return jsonify({'authenticated': True, 'username': user.username})
    return jsonify({'authenticated': False})


# ---------------------------------------------------------------------------
# МОДЕЛЬ ЗАМЕТКИ (ORM-класс таблицы note)
# ---------------------------------------------------------------------------

# Каждый атрибут класса = колонка таблицы в базе данных.
# db.Column(тип, параметры) описывает столбец.
class User(db.Model):
    """
    Модель пользователя (авторизация).

    Пароль хранится ТОЛЬКО в виде хэша (generate_password_hash),
    сам пароль в базу не попадает.
    """

    id = db.Column(db.Integer, primary_key=True)                 # уникальный id пользователя
    username = db.Column(db.String(80), unique=True, nullable=False)  # логин (уникальный)
    password_hash = db.Column(db.String(255), nullable=False)    # хэш пароля (с солью)


class Note(db.Model):
    """
    Модель заметки на «доске объявлений».

    Помимо пользовательских полей (title, content, author...) содержит
    большой набор служебных колонок с данными о посетителе, который
    оставил заметку (IP, геолокация, браузер, устройство и т.д.).
    """

    # --- Основные (пользовательские) поля заметки ---

    id = db.Column(db.Integer, primary_key=True)        # уникальный числовой id (автоинкремент)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # кто оставил заметку (null — старые/анонимные)
    title = db.Column(db.String(100), nullable=False)   # заголовок заметки (не может быть пустым)
    content = db.Column(db.Text, nullable=False)        # текст заметки (Text — длинный текст)
    author = db.Column(db.String(100), default='Аноним')  # автор; по умолчанию «Аноним»
    font_color = db.Column(db.String(20), default='#000000')  # цвет текста заметки (hex-код)
    font_size = db.Column(db.Integer, default=16)       # размер шрифта заметки в пикселях
    created_at = db.Column(db.DateTime, default=datetime.utcnow)  # дата и время публикации

    # --- Сетевая информация о посетителе ---

    ip = db.Column(db.String(45))     # IP-адрес посетителя (45 симв. — максимум для IPv6)
    port = db.Column(db.String(10))   # TCP-порт, с которого пришёл запрос

    # --- Геолокация (берётся у внешнего сервиса ip-api.com по IP) ---

    geo_country = db.Column(db.String(100))  # страна
    geo_city = db.Column(db.String(100))     # город
    geo_isp = db.Column(db.String(200))      # интернет-провайдер (ISP)
    geo_as = db.Column(db.String(200))       # автономная система (ASN)
    is_vpn = db.Column(db.Boolean)           # похоже ли на VPN/прокси/хостинг

    # --- Данные из User-Agent (браузер и устройство) ---

    browser = db.Column(db.String(50))           # название браузера (Chrome, Firefox...)
    browser_version = db.Column(db.String(50))   # версия браузера
    os = db.Column(db.String(50))                # операционная система
    os_version = db.Column(db.String(50))        # версия ОС
    device_type = db.Column(db.String(20))       # тип устройства: desktop/mobile/tablet
    engine = db.Column(db.String(20))            # движок браузера (Blink, WebKit, Gecko)

    # --- Откуда пришёл посетитель ---

    referer = db.Column(db.Text)   # URL страницы, с которой был переход
    origin = db.Column(db.Text)    # заголовок Origin запроса

    # --- «Паспорт» устройства, присланный из JavaScript (collectClientInfo) ---

    screen_res = db.Column(db.String(30))     # разрешение экрана, напр. "1920x1080"
    color_depth = db.Column(db.Integer)       # глубина цвета в битах
    pixel_ratio = db.Column(db.Float)         # ratio физических/логических пикселей
    window_size = db.Column(db.String(30))    # размер окна браузера, напр. "1536x719"
    cpu_cores = db.Column(db.Integer)         # число логических ядер CPU
    ram_gb = db.Column(db.Float)              # объём оперативной памяти в ГБ
    gpu = db.Column(db.String(200))           # модель видеокарты (из WebGL)
    network_type = db.Column(db.String(20))   # тип сети (4g, 3g, wifi...)
    downlink = db.Column(db.Float)            # скорость загрузки в Мбит/с
    rtt = db.Column(db.Integer)               # задержка сети (round-trip time) в мс
    battery_level = db.Column(db.Float)       # уровень заряда батареи от 0 до 1
    battery_charging = db.Column(db.Boolean)  # идёт ли зарядка
    accounts = db.Column(db.Text)             # сохранённые аккаунты (JSON-строка)

    def to_dict(self):
        """
        Преобразует объект заметки в обычный словарь (dict).

        Нужно для передачи данных в JSON-ответе: jsonify не умеет
        сериализовывать ORM-объекты напрямую, поэтому вручную собираем
        словарь из всех полей.

        Особенности:
          - created_at (объект datetime) переводим в ISO-строку,
            чтобы JSON мог его представить; если даты нет — None.
          - Boolean-поля (is_vpn, battery_charging) тоже кладём как есть —
            jsonify сам преобразует их в true/false.

        Возвращает: словарь, где ключи — имена полей, значения — данные.
        """
        return {
            'id': self.id,
            'user_id': self.user_id,
            'title': self.title,
            'content': self.content,
            'author': self.author,
            'font_color': self.font_color,
            'font_size': self.font_size,
            # isoformat() даёт строку вида "2026-08-10T12:34:56.789123"
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
            'accounts': self.accounts,
        }


# ---------------------------------------------------------------------------
# СОЗДАНИЕ ТАБЛИЦ И «ЛЁГКАЯ МИГРАЦИЯ» СТАРОЙ БАЗЫ ДАННЫХ
# ---------------------------------------------------------------------------

# Список колонок, которых может не быть в старой версии базы.
# Каждый элемент: (имя_колонки, SQL-тип). Нужен, чтобы при запуске
# автоматически добавить недостающие столбцы в уже существующую таблицу.
NEW_COLUMNS = [
    ('created_at', 'DATETIME'),                       # дата публикации
    ('user_id', 'INTEGER'),                            # автор заметки (id пользователя)
    ('author', "VARCHAR(100) DEFAULT 'Аноним'"),      # автор со значением по умолчанию
    ('font_color', "VARCHAR(20) DEFAULT '#000000'"),  # цвет текста
    ('font_size', 'INTEGER DEFAULT 16'),              # размер шрифта
    ('ip', 'VARCHAR(45)'),                            # IP-адрес
    ('port', 'VARCHAR(10)'),                          # порт
    ('geo_country', 'VARCHAR(100)'),                  # страна
    ('geo_city', 'VARCHAR(100)'),                     # город
    ('geo_isp', 'VARCHAR(200)'),                      # провайдер
    ('geo_as', 'VARCHAR(200)'),                       # автономная система
    ('is_vpn', 'BOOLEAN'),                            # признак VPN/прокси
    ('browser', 'VARCHAR(50)'),                       # браузер
    ('browser_version', 'VARCHAR(50)'),               # версия браузера
    ('os', 'VARCHAR(50)'),                            # ОС
    ('os_version', 'VARCHAR(50)'),                    # версия ОС
    ('device_type', 'VARCHAR(20)'),                   # тип устройства
    ('engine', 'VARCHAR(20)'),                        # движок браузера
    ('referer', 'TEXT'),                              # страница-источник
    ('origin', 'TEXT'),                               # Origin-заголовок
    ('screen_res', 'VARCHAR(30)'),                    # разрешение экрана
    ('color_depth', 'INTEGER'),                       # глубина цвета
    ('pixel_ratio', 'FLOAT'),                         # пиксель-ратио
    ('window_size', 'VARCHAR(30)'),                   # размер окна
    ('cpu_cores', 'INTEGER'),                         # ядра CPU
    ('ram_gb', 'FLOAT'),                              # объём RAM
    ('gpu', 'VARCHAR(200)'),                          # видеокарта
    ('network_type', 'VARCHAR(20)'),                  # тип сети
    ('downlink', 'FLOAT'),                            # скорость соединения
    ('rtt', 'INTEGER'),                               # задержка сети
    ('battery_level', 'FLOAT'),                       # заряд батареи
    ('battery_charging', 'BOOLEAN'),                  # идёт ли зарядка
    ('accounts', 'TEXT'),                             # аккаунты (JSON)
]

# Всё выполняется внутри app_context: иначе Flask/SQLAlchemy не знают,
# в каком приложении работаем (нужно для create_all и запросов).
# Если инициализация БД падает — записываем трейсбек в error.log
# (это происходит на этапе импорта, когда @app.errorhandler ещё не
# зарегистрирован, поэтому используем вспомогательную функцию) и
# прерываем запуск.
try:
    with app.app_context():
        # Создаём все таблицы, которые описаны моделями (если их ещё нет).
        db.create_all()

        # Импортируем text для выполнения «сырого» SQL-запроса.
        from sqlalchemy import text

        # PRAGMA table_info(note) возвращает метаданные таблицы note.
        # Извлекаем список существующих имён колонок (вторая позиция каждого ряда).
        cols = [row[1] for row in db.session.execute(text("PRAGMA table_info(note)")).fetchall()]

        added = []  # сюда запомним, какие колонки только что добавили

        # Для каждой колонки из списка NEW_COLUMNS:
        # если её ещё нет в таблице — добавляем через ALTER TABLE.
        for col, ctype in NEW_COLUMNS:
            if col not in cols:
                db.session.execute(text(f"ALTER TABLE note ADD COLUMN {col} {ctype}"))
                added.append(col)

        # Если колонку created_at добавили только сейчас — заполняем у всех
        # существующих записей текущим временем (иначе там был бы NULL).
        if 'created_at' in added:
            Note.query.update({Note.created_at: datetime.utcnow()})

        # Если колонки author/font_color/font_size появились только что —
        # проставляем старым записям значения по умолчанию.
        if 'author' in added:
            Note.query.update({Note.author: 'Аноним', Note.font_color: '#000000', Note.font_size: 16})

        # Фиксируем все изменения в базе (коммит транзакции).
        db.session.commit()
except Exception:
    log_error_message('Ошибка инициализации базы данных:\n' + traceback.format_exc())
    raise


# ---------------------------------------------------------------------------
# ПАРСИНГ USER-AGENT (без внешних библиотек)
# ---------------------------------------------------------------------------

def parse_user_agent(ua):
    """
    Определяет браузер, ОС и тип устройства из строки User-Agent.

    User-Agent — это заголовок HTTP-запроса, который браузер присылает
    автоматически. В нём, как правило, перечислены и браузер, и ОС.
    Парсим его вручную с помощью регулярных выражений, чтобы не
    подтягивать тяжёлую библиотеку типа ua-parser.

    Порядок проверок важен: например, Edge и Opera содержат в своём
    User-Agent также подстроку "Chrome/", поэтому их надо проверять
    ДО Chrome, иначе они будут определены неверно.

    Параметры:
        ua (str): строка User-Agent из заголовка запроса.

    Возвращает:
        dict с ключами browser, browser_version, os, os_version,
        device_type, engine.
    """
    # На случай отсутствия заголовка — не падаем, используем пустую строку.
    ua = ua or ''

    # Словарь с результатами. По умолчанию всё «Unknown»,
    # device_type — desktop (самый распространённый случай).
    result = {
        'browser': 'Unknown',
        'browser_version': None,
        'os': 'Unknown',
        'os_version': None,
        'device_type': 'desktop',
        'engine': 'Unknown',
    }

    # --- Определение типа устройства по маркерам из User-Agent ---

    if 'Mobi' in ua:
        result['device_type'] = 'mobile'          # признак мобильного устройства
    elif 'Tablet' in ua or 'iPad' in ua:
        result['device_type'] = 'tablet'          # планшет

    # --- Определение операционной системы ---

    if 'Windows' in ua:
        result['os'] = 'Windows'
        # Версия Windows закодирована как "Windows NT X.Y", например
        # Windows NT 10.0 (Windows 10/11). Извлекаем версию.
        m = re.search(r'Windows NT (\d+\.?\d*)', ua)
        if m:
            result['os_version'] = m.group(1)
    elif 'Android' in ua:
        result['os'] = 'Android'
        # Версия Android пишется сразу после слова Android: "Android 13".
        m = re.search(r'Android (\d+\.?\d*)', ua)
        if m:
            result['os_version'] = m.group(1)
    elif 'iPhone' in ua or 'iPad' in ua:
        result['os'] = 'iOS'
        # В User-Agent версия iOS выглядит как "iPhone OS 16_5"
        # (символы подчёркивания вместо точек), поэтому заменяем _ на .
        m = re.search(r'iPhone OS (\d+[_\d]*)', ua)
        if m:
            result['os_version'] = m.group(1).replace('_', '.')
    elif 'Mac OS X' in ua or 'Macintosh' in ua:
        result['os'] = 'macOS'
        # Версия macOS: "Mac OS X 10_15_7" — тоже с подчёркиваниями.
        m = re.search(r'Mac OS X (\d+[_\d.]*)', ua)
        if m:
            result['os_version'] = m.group(1).replace('_', '.')
    elif 'CrOS' in ua:
        result['os'] = 'ChromeOS'   # маркер Chrome OS
    elif 'Linux' in ua:
        result['os'] = 'Linux'      # просто Linux

    # --- Определение браузера и его движка ---

    # Edge: в UA есть и "Edg/", и "Chrome/", поэтому проверяем первым.
    if 'Edg/' in ua:
        result['browser'] = 'Edge'
        result['engine'] = 'Blink'                  # Edge построен на Chromium (Blink)
        m = re.search(r'Edg/(\d+)', ua)
        if m:
            result['browser_version'] = m.group(1)

    # Opera: тоже содержит "Chrome/", поэтому проверяем до Chrome.
    elif 'OPR/' in ua:
        result['browser'] = 'Opera'
        result['engine'] = 'Blink'
        m = re.search(r'OPR/(\d+)', ua)
        if m:
            result['browser_version'] = m.group(1)

    elif 'Firefox/' in ua:
        result['browser'] = 'Firefox'
        result['engine'] = 'Gecko'                  # движок Mozilla
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
        # Версия Safari указывается не после "Safari/", а в "Version/".
        m = re.search(r'Version/(\d+)', ua)
        if m:
            result['browser_version'] = m.group(1)

    elif 'Trident/' in ua or 'MSIE' in ua:
        result['browser'] = 'IE'        # старый Internet Explorer
        result['engine'] = 'Trident'

    return result


# ---------------------------------------------------------------------------
# ГЕОЛОКАЦИЯ ПО IP (бесплатный сервис ip-api.com)
# ---------------------------------------------------------------------------

def geo_by_ip(ip):
    """
    Определяет географию посетителя по его IP-адресу.

    Используется бесплатный сервис http://ip-api.com/json/<ip> (без ключа,
    только HTTP-запрос). Сервис возвращает страну, город, провайдера и т.д.

    Параметры:
        ip (str): IP-адрес посетителя.

    Возвращает:
        dict с данными геолокации при успешном ответе, иначе None.
    """
    # Если IP нет или он из «частных» диапазонов — геолокация бессмысленна
    # (локальная сеть, localhost). К частным относятся:
    #   127.* (localhost), 10.* (локальная сеть), 192.168.*, 172.16.*,
    #   а также IPv6 ::1 (localhost) и ::ffff:127 (IPv4-mapped localhost).
    if not ip or ip.startswith(('127.', '10.', '192.168.', '172.16.', '::1', '::ffff:127')):
        return None

    try:
        # Делаем GET-запрос к внешнему сервису.
        # params={'fields': ...} просит вернуть только нужные поля,
        # чтобы не качать лишнее: статус, страна, город, провайдер,
        # AS, флаги proxy и hosting.
        # timeout=3 — не ждать ответа дольше 3 секунд.
        r = requests.get(
            f'http://ip-api.com/json/{ip}',
            params={'fields': 'status,country,city,isp,as,proxy,hosting'},
            timeout=3
        )
        d = r.json()  # разбираем JSON-ответ

        # status == "success" — сервис нашёл данные по IP.
        if d.get('status') == 'success':
            return d
    except Exception:
        # Сеть недоступна, сервис упал или вернул не JSON —
        # молча игнорируем и возвращаем None (гео не критично).
        pass
    return None


# ---------------------------------------------------------------------------
# ЭВРИСТИКА ОПРЕДЕЛЕНИЯ VPN / ПРОКСИ / ХОСТИНГА
# ---------------------------------------------------------------------------

# Список ключевых слов, по которым определяем, что провайдер/ASN — это,
# скорее всего, VPN-сервис, прокси или облачный хостинг, а не
# «домашний» интернет-провайдер.
VPN_KEYWORDS = ['hosting', 'cloud', 'datacenter', 'data center', 'vpn', 'proxy',
                'digitalocean', 'ovh', 'amazon', 'aws', 'google cloud', 'azure',
                'hetzner', 'linode', 'vultr', 'leaseweb', 'server']


def detect_vpn(isp, as_):
    """
    Грубая эвристика: похоже ли имя провайдера (ISP) или автономной
    системы (AS) на VPN/прокси/хостинг.

    Просто проверяем, встречается ли хоть одно ключевое слово из
    VPN_KEYWORDS в названии провайдера или ASN (в нижнем регистре).

    Параметры:
        isp (str): название интернет-провайдера.
        as_ (str): название автономной системы.

    Возвращает:
        bool: True, если нашлось совпадение с ключевыми словами.
    """
    # Склеиваем оба названия и приводим к нижнему регистру —
    # чтобы сравнение было регистронезависимым.
    haystack = f'{isp or ""} {as_ or ""}'.lower()

    # any() вернёт True, если хотя бы одно ключевое слово встретилось.
    return any(k in haystack for k in VPN_KEYWORDS)


# ---------------------------------------------------------------------------
# REST API: ПОЛУЧЕНИЕ СПИСКА ЗАМЕТОК
# ---------------------------------------------------------------------------

# Маршрут /notes, доступен только для HTTP-метода GET.
@app.route('/notes', methods=['GET'])
def get_notes():
    """
    Возвращает JSON-список всех заметок.

    Сортировка: сначала самые свежие (created_at по убыванию),
    при одинаковом времени — с большим id (id.desc()).
    """
    notes = Note.query.order_by(Note.created_at.desc(), Note.id.desc()).all()
    # Преобразуем каждый ORM-объект в словарь и оборачиваем в JSON-ответ.
    return jsonify([n.to_dict() for n in notes])


# ---------------------------------------------------------------------------
# REST API: СОЗДАНИЕ НОВОЙ ЗАМЕТКИ
# ---------------------------------------------------------------------------

# Тот же маршрут /notes, но для HTTP-метода POST (создание).
@app.route('/notes', methods=['POST'])
@login_required  # только авторизованные пользователи могут оставлять заметки
def create_note():
    """
    Создаёт новую заметку из данных, присланных клиентом в JSON.

    Помимо пользовательских полей (title, content...) собирает
    «паспорт» посетителя: IP, порт, геолокацию, данные из User-Agent
    и метаданные устройства, присланные JavaScript'ом.

    Возвращает: JSON созданной заметки и HTTP-код 201 (Created).
    """
    # Разбираем JSON-тело запроса в Python-словарь.
    data = request.get_json()

    # Текущий пользователь (гарантирован декоратором login_required).
    current_user = get_current_user()

    # IP и порт клиента берутся из самого HTTP-запроса.
    ip = request.remote_addr                     # IP-адрес клиента
    port = request.environ.get('REMOTE_PORT')    # исходный TCP-порт клиента

    # Парсим заголовок User-Agent, чтобы узнать браузер и ОС.
    ua = parse_user_agent(request.headers.get('User-Agent'))

    # Определяем геолокацию по IP; при неудаче подставляем пустой словарь,
    # чтобы не проверять на None ниже (geo.get(...) безопасен).
    geo = geo_by_ip(ip) or {}

    # Создаём новый объект Note с заполнением всех колонок.
    new_note = Note(
        # --- Пользовательские данные из формы ---
        user_id=current_user.id,                              # кто оставил заметку
        title=data['title'],                                  # заголовок (обязательное поле, без .get)
        content=data['content'],                              # текст заметки
        # Автор: если пользователь ввёл — берём его, иначе логин пользователя.
        author=current_user.username,   # автор заметки — ник из сессии (поле ввода убрано)
        font_color=data.get('font_color') or '#000000',       # цвет текста
        font_size=data.get('font_size') or 16,                # размер шрифта

        # --- Сетевые данные клиента ---
        ip=ip,
        port=str(port) if port else None,

        # --- Геолокация и признак VPN ---
        geo_country=geo.get('country'),   # страна
        geo_city=geo.get('city'),         # город
        geo_isp=geo.get('isp'),           # провайдер
        geo_as=geo.get('as'),             # автономная система
        is_vpn=detect_vpn(geo.get('isp'), geo.get('as')),  # эвристика VPN/прокси

        # --- Данные из User-Agent ---
        browser=ua['browser'],
        browser_version=ua['browser_version'],
        os=ua['os'],
        os_version=ua['os_version'],
        device_type=ua['device_type'],
        engine=ua['engine'],

        # --- Откуда пришёл запрос ---
        referer=request.referrer,                        # предыдущая страница
        origin=request.headers.get('Origin'),            # Origin-заголовок

        # --- Метаданные устройства из JavaScript (collectClientInfo) ---
        screen_res=data.get('screen_res'),   # разрешение экрана
        color_depth=data.get('color_depth'), # глубина цвета
        pixel_ratio=data.get('pixel_ratio'), # пиксель-ратио
        window_size=data.get('window_size'), # размер окна
        cpu_cores=data.get('cpu_cores'),     # ядра CPU
        ram_gb=data.get('ram_gb'),           # объём RAM
        gpu=data.get('gpu'),                 # видеокарта
        network_type=data.get('network_type'),  # тип сети
        downlink=data.get('downlink'),       # скорость соединения
        rtt=data.get('rtt'),                 # задержка сети
        battery_level=data.get('battery_level'),        # заряд батареи
        battery_charging=data.get('battery_charging'),  # идёт ли зарядка

        # Поле accounts приходит из JS как список объектов.
        # Сериализуем его в JSON-строку для хранения в TEXT-колонке;
        # ensure_ascii=False — сохраняем кириллицу читаемым текстом.
        accounts=json.dumps(data.get('accounts'), ensure_ascii=False) if data.get('accounts') else None,
    )

    # Добавляем объект в сессию (транзакцию) БД...
    db.session.add(new_note)
    # ...и фиксируем (commit) — только после этого запись реально сохраняется.
    db.session.commit()

    # Возвращаем созданную заметку в JSON и код 201 «Created»
    # (201 — стандартный код ответа на успешное создание ресурса).
    return jsonify(new_note.to_dict()), 201


# ---------------------------------------------------------------------------
# REST API: УДАЛЕНИЕ ЗАМЕТКИ
# ---------------------------------------------------------------------------

# Маршрут с параметром <int:id> в URL; int — конвертер Flask,
# который автоматически преобразует строку в целое число.
@app.route('/notes/<int:id>', methods=['DELETE'])
@login_required  # удалять могут только авторизованные пользователи
def delete_note(id):
    """
    Удаляет заметку по её id.

    Параметры:
        id (int): идентификатор заметки из URL.

    Возвращает: пустой ответ с кодом 204 (No Content).
    Если заметка не найдена — Flask вернёт 404 (get_or_404).
    """
    # get_or_404: ищем заметку по первичному ключу; если не нашли —
    # автоматически отвечаем ошибкой 404 Not Found.
    note = Note.query.get_or_404(id)

    # Помечаем объект на удаление...
    db.session.delete(note)
    # ...и фиксируем транзакцию (удаление применяется к базе).
    db.session.commit()

    # 204 No Content — успешный ответ без тела (тело не требуется).
    return '', 204


# ---------------------------------------------------------------------------
# ЗАПУСК ПРИЛОЖЕНИЯ
# ---------------------------------------------------------------------------

# Условие выполняется только при прямом запуске файла (python app.py),
# а не при импорте модуля (например, через gunicorn/фласк-команду).
if __name__ == '__main__':
    # debug=True включает авто-перезагрузку при изменениях кода
    # и страницу с подробными ошибками. Только для разработки!
    app.run(debug=True)
