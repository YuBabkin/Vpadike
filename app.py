from flask import Flask, jsonify, render_template

app = Flask(__name__)

count = 0


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/inc')
def inc():
    global count
    count += 1
    return jsonify(count=count)


if __name__ == '__main__':
    app.run(debug=True)
