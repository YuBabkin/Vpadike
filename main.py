import sqlite3
from datetime import datetime

from flask import Flask, jsonify, request, render_template

app = Flask(__name__)
DB = "notes.db"


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            text TEXT NOT NULL
        )"""
    )
    conn.commit()
    conn.close()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/notes", methods=["GET"])
def get_notes():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, created_at, text FROM notes ORDER BY id DESC LIMIT 100"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/notes", methods=["POST"])
def add_note():
    data = request.get_json()
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "text is required"}), 400
    conn = get_db()
    now = datetime.now().isoformat()
    conn.execute("INSERT INTO notes (created_at, text) VALUES (?, ?)", (now, text))
    conn.commit()
    conn.close()
    return jsonify({"ok": True}), 201


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
