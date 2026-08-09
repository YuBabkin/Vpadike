import os
from datetime import datetime
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

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'content': self.content,
            'author': self.author,
            'font_color': self.font_color,
            'font_size': self.font_size,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

# Создаём таблицы (при первом запуске)
with app.app_context():
    db.create_all()
    from sqlalchemy import text
    cols = [row[1] for row in db.session.execute(text("PRAGMA table_info(note)")).fetchall()]
    if 'created_at' not in cols:
        db.session.execute(text("ALTER TABLE note ADD COLUMN created_at DATETIME"))
        Note.query.update({Note.created_at: datetime.utcnow()})
        db.session.commit()
    if 'author' not in cols:
        db.session.execute(text("ALTER TABLE note ADD COLUMN author VARCHAR(100) DEFAULT 'Аноним'"))
        db.session.execute(text("ALTER TABLE note ADD COLUMN font_color VARCHAR(20) DEFAULT '#000000'"))
        db.session.execute(text("ALTER TABLE note ADD COLUMN font_size INTEGER DEFAULT 16"))
        Note.query.update({Note.author: 'Аноним', Note.font_color: '#000000', Note.font_size: 16})
        db.session.commit()
    
    

# Эндпоинт: получить все заметки
@app.route('/notes', methods=['GET'])
def get_notes():
    notes = Note.query.order_by(Note.created_at.desc(), Note.id.desc()).all()
    return jsonify([n.to_dict() for n in notes])

# Эндпоинт: создать заметку
@app.route('/notes', methods=['POST'])
def create_note():
    data = request.get_json()
    new_note = Note(
        title=data['title'],
        content=data['content'],
        author=data.get('author') or 'Аноним',
        font_color=data.get('font_color') or '#000000',
        font_size=data.get('font_size') or 16
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
