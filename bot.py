import asyncio
import aiohttp
import websockets
import json
import os
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

# Configuration Constants
PRIVATE_KEY = os.getenv('PRIVATE_KEY', '')
CHAIN_ID = int(os.getenv('POLYGON_CHAIN_ID', '137'))
HOST = "https://clob.polymarket.com"
WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
GAMMA_API = "https://gamma-api.polymarket.com"
ORDER_SIZE = 10
SNIPE_PRICE = 0.99
DRY_RUN_MODE = True

class MarketScanner:
    def __init__(self):
        self.session = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def get_market_details(self, market_id):
        url = f"{GAMMA_API}/markets/{market_id}"
        try:
            async with self.session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    clob_token_ids = data.get('clobTokenIds') or data.get('clob_token_ids')
                    if isinstance(clob_token_ids, str):
                        clob_token_ids = json.loads(clob_token_ids)
                        data['clobTokenIds'] = clob_token_ids
                    return data
        except: pass
        return None
    
    def get_current_slot_slug(self):
        now_utc = datetime.now(timezone.utc)
        est = timezone(timedelta(hours=-5))
        now_est = now_utc.astimezone(est)
        current_minute = now_est.minute
        slot_minute = (current_minute // 15) * 15
        current_slot_est = now_est.replace(minute=slot_minute, second=0, microsecond=0)
        
        slots = []
        for i in range(-1, 3):
            slot_start_est = current_slot_est + timedelta(minutes=15*i)
            start_timestamp = int(slot_start_est.timestamp())
            slug = f'btc-updown-15m-{start_timestamp}'
            slot_start_utc = datetime.fromtimestamp(start_timestamp, tz=timezone.utc)
            slot_end_utc = slot_start_utc + timedelta(minutes=15)
            slots.append({'slug': slug, 'end_time': slot_end_utc, 'start_time': slot_start_utc})
        return slots
    
    async def fetch_market_by_slug(self, slug):
        url = f"{GAMMA_API}/markets/slug/{slug}"
        try:
            async with self.session.get(url, timeout=10) as response:
                if response.status == 200:
                    return await response.json()
        except: pass
        return None
    
    async def find_active_15m_market(self):
        slots = self.get_current_slot_slug()
        now_utc = datetime.now(timezone.utc)
        
        for slot in slots:
            start_time, end_time = slot['start_time'], slot['end_time']
            time_to_end = (end_time - now_utc).total_seconds() / 60
            time_to_start = (start_time - now_utc).total_seconds() / 60
            
            if time_to_start < 0 and time_to_end > -0.5:
                market = await self.fetch_market_by_slug(slot['slug'])
                if market:
                    market_id = market.get('id')
                    if market_id:
                        full_market = await self.get_market_details(market_id)
                        if full_market:
                            clob_token_ids = full_market.get('clobTokenIds', [])
                            if len(clob_token_ids) >= 2:
                                outcomes = full_market.get('outcomes', ['Up', 'Down'])
                                if isinstance(outcomes, str):
                                    outcomes = json.loads(outcomes)
                                full_market.update({
                                    '_time_remaining_minutes': time_to_end,
                                    '_end_time': end_time,
                                    '_start_time': start_time,
                                    '_condition_id': market.get('conditionId')
                                })
                                return full_market
        return None

class PriceStreamer:
    def __init__(self, token_ids, market_id, sniper, socketio):
        self.token_ids = token_ids
        self.market_id = market_id
        self.sniper = sniper
        self.socketio = socketio
        self.ws = None
        self.running = False
        self.orderbook = {}
    
    async def connect(self):
        try:
            self.ws = await websockets.connect(WS_URL)
            await self.ws.send(json.dumps({"assets_ids": self.token_ids, "type": "market"}))
            self.socketio.emit('status', {'message': 'WebSocket Connected', 'type': 'connected'})
            self.socketio.emit('log', {'message': '[OK] Connected to price feed', 'type': 'success'})
            self.running = True
            await self.listen()
        except Exception as e:
            self.socketio.emit('log', {'message': f'[ERROR] WebSocket: {e}', 'type': 'error'})
    
    async def handle_book_message(self, data):
        asset_id = data.get('asset_id')
        bids, asks = data.get('bids'), data.get('asks')
        if asset_id and bids and asks:
            best_bid, best_ask = float(bids[0]['price']), float(asks[0]['price'])
            self.orderbook[asset_id] = {'bid': best_bid, 'ask': best_ask, 'mid': (best_bid + best_ask) / 2}
            await self.sniper.on_price_update(asset_id, self.orderbook[asset_id])
    
    async def handle_price_change_message(self, data):
        for change in data.get('price_changes', []):
            asset_id = change.get('asset_id')
            if asset_id:
                best_bid, best_ask = float(change.get('best_bid', 0)), float(change.get('best_ask', 0))
                if best_bid > 0 and best_ask > 0:
                    self.orderbook[asset_id] = {'bid': best_bid, 'ask': best_ask, 'mid': (best_bid + best_ask) / 2}
                    await self.sniper.on_price_update(asset_id, self.orderbook[asset_id])
    
    async def listen(self):
        while self.running:
            try:
                message = await asyncio.wait_for(self.ws.recv(), timeout=15)
                data = json.loads(message)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            event_type = item.get('event_type')
                            if event_type == 'book':
                                await self.handle_book_message(item)
                            elif event_type == 'price_change':
                                await self.handle_price_change_message(item)
                elif isinstance(data, dict):
                    event_type = data.get('event_type')
                    if event_type == 'book':
                        await self.handle_book_message(data)
                    elif event_type == 'price_change':
                        await self.handle_price_change_message(data)
            except asyncio.TimeoutError:
                try:
                    await self.ws.send(json.dumps({"type": "ping"}))
                except: break
            except: break
    
    async def close(self):
        self.running = False
        if self.ws:
            await self.ws.close()

class LastSecondSniper:
    def __init__(self, market, socketio, stats):
        self.market = market
        self.socketio = socketio
        self.stats = stats
        self.end_time = market['_end_time']
        outcomes = market.get('outcomes', ['Up', 'Down'])
        if isinstance(outcomes, str):
            outcomes = json.loads(outcomes)
        self.outcomes = outcomes
        
        clob_token_ids = market.get('clobTokenIds', [])
        if isinstance(clob_token_ids, str):
            clob_token_ids = json.loads(clob_token_ids)
        
        self.token_map = {}
        for i, token_id in enumerate(clob_token_ids):
            outcome = outcomes[i] if i < len(outcomes) else f"Outcome {i}"
            self.token_map[token_id] = {'outcome': outcome, 'index': i}
        
        self.orderbook_data = {}
        self.winning_side = None
        self.winning_price = None
        self.sniped = False
        self.last_display_time = 0
    
    def get_time_remaining(self):
        return max(0, (self.end_time - datetime.now(timezone.utc)).total_seconds())
    
    async def on_price_update(self, token_id, orderbook):
        self.orderbook_data[token_id] = orderbook
        time_remaining = self.get_time_remaining()
        
        if len(self.orderbook_data) >= 2:
            for tid, book in self.orderbook_data.items():
                if book['mid'] > 0.50:
                    self.winning_side = tid
                    self.winning_price = book['ask']
        
        current_time = datetime.now(timezone.utc).timestamp()
        if current_time - self.last_display_time >= (2 if time_remaining <= 10 else 5):
            self.last_display_time = current_time
            ui_data = {}
            for tid, book in self.orderbook_data.items():
                outcome = self.token_map[tid]['outcome']
                ui_data[outcome] = {'bid': book['bid'] * 100, 'ask': book['ask'] * 100, 'mid': book['mid'] * 100}
            self.socketio.emit('price_update', ui_data)
        
        if time_remaining <= 1 and not self.sniped:
            await self.execute_snipe()
    
    async def execute_snipe(self):
        if self.sniped:
            return
        self.sniped = True
        
        if not self.winning_side or not self.winning_price:
            self.socketio.emit('log', {'message': '[WARN] No winning side', 'type': 'warning'})
            return
        
        outcome = self.token_map.get(self.winning_side, {}).get('outcome', 'Unknown')
        self.socketio.emit('snipe_executed', {'message': f'SNIPE! {outcome} @ ${self.winning_price:.4f}'})
        
        if self.winning_price < SNIPE_PRICE:
            profit = (1.0 - self.winning_price) * ORDER_SIZE
            self.stats['profitLoss'] += profit
            self.stats['successful'] += 1
            self.socketio.emit('log', {'message': f'[PAPER] {outcome} | +${profit:.2f}', 'type': 'success'})
        else:
            self.socketio.emit('log', {'message': f'[WARN] Price too high: ${self.winning_price:.4f}', 'type': 'warning'})
        
        self.stats['totalSnipes'] += 1
        self.socketio.emit('stats_update', self.stats)

async def run_bot_loop(socketio, state_container):
    while state_container['bot_running']:
        market = None
        socketio.emit('status', {'message': 'Scanning...', 'type': 'searching'})
        socketio.emit('log', {'message': '[SEARCH] Scanning market...', 'type': 'info'})
        
        while not market and state_container['bot_running']:
            async with MarketScanner() as scanner:
                market = await scanner.find_active_15m_market()
            if market:
                break
            await asyncio.sleep(2)
        
        if not market or not state_container['bot_running']:
            break
        
        clob_token_ids = market.get('clobTokenIds', [])
        if isinstance(clob_token_ids, str):
            clob_token_ids = json.loads(clob_token_ids)
        
        if len(clob_token_ids) < 2:
            continue
        
        market_id = market.get('_condition_id') or market.get('conditionId')
        if not market_id:
            continue
        
        socketio.emit('log', {'message': f'[FOUND] {market.get("question")}', 'type': 'success'})
        socketio.emit('market_found', {
            'question': market.get('question', 'Bitcoin 15m'),
            'endTime': market['_end_time'].isoformat(),
            'orderSize': ORDER_SIZE
        })
        
        sniper = LastSecondSniper(market, socketio, state_container['stats'])
        streamer = PriceStreamer(clob_token_ids, market_id, sniper, socketio)
        
        try:
            await streamer.connect()
        except: pass
        finally:
            await streamer.close()
        
        if state_container['bot_running']:
            socketio.emit('log', {'message': '[NEXT] Market closed', 'type': 'info'})
            await asyncio.sleep(2)