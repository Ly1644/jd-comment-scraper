from flask import Flask, jsonify
import os

app = Flask(__name__)

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'ok',
        'message': '服务运行正常',
        'version': '1.0.0'
    })

@app.route('/', methods=['GET'])
def index():
    return jsonify({'hello': 'world'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
