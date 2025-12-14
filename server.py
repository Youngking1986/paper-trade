from flask import Flask, render_template
from flask_socketio import SocketIO, emit
import asyncio
import threading
import os
from bot import run_bot_loop, DRY_RUN_MODE

# Flask setup
app = Flask(__name__)
app.config['SECRET_KEY'] = 'polymarket-sniper-secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Global state container
state = {
    'bot_running': False,
    'stats': {'totalSnipes': 0, 'successful': 0, 'profitLoss': 0.0}
}

def start_bot_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_bot_loop(socketio, state))

# Flask routes
@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('start_bot')
def handle_start():
    if not state['bot_running']:
        state['bot_running'] = True
        emit('log', {'message': '[START] Bot started', 'type': 'success'})
        threading.Thread(target=start_bot_thread, daemon=True).start()

@socketio.on('stop_bot')
def handle_stop():
    state['bot_running'] = False
    emit('log', {'message': '[STOP] Bot stopped', 'type': 'warning'})
    emit('status', {'message': 'Disconnected', 'type': 'disconnected'})

if __name__ == '__main__':
    print("\n" + "="*70)
    print("POLYMARKET SNIPER WEB SERVER")
    print("="*70)
    print(f"Mode: {'PAPER TRADING' if DRY_RUN_MODE else 'LIVE TRADING'}")
    print("\n>>> Open: http://localhost:5000")
    print("="*70 + "\n")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)