const socket = io();
let marketEndTime = null;
let timerInterval = null;

socket.on('log', d => addLog(d.message, d.type));
socket.on('status', d => {
    document.getElementById('statusIndicator').className = `status-indicator ${d.type}`;
    document.getElementById('connectionStatus').textContent = d.message;
});
socket.on('market_found', d => {
    marketEndTime = new Date(d.endTime);
    document.getElementById('marketInfo').innerHTML = `<div style="font-weight:600">${d.question}</div><div style="margin-top:8px">Ends: ${new Date(d.endTime).toLocaleTimeString()}</div>`;
    startTimer();
});
socket.on('price_update', d => {
    let html = '';
    for (const [outcome, book] of Object.entries(d)) {
        const win = book.mid > 50;
        const emoji = outcome.toLowerCase().includes('up') ? '⬆️' : '⬇️';
        html += `<div class="outcome-card ${win?'winning':''}">
            <div style="font-weight:600;margin-bottom:12px">${emoji} ${outcome}</div>
            <div class="price-row"><span>Bid:</span><span class="price-value">${book.bid.toFixed(2)}%</span></div>
            <div class="price-row"><span>Ask:</span><span class="price-value">${book.ask.toFixed(2)}%</span></div>
            <div class="price-row"><span>Mid:</span><span class="price-value mid">${book.mid.toFixed(2)}%</span></div>
        </div>`;
    }
    document.getElementById('orderbookContainer').innerHTML = html;
});
socket.on('stats_update', d => {
    document.getElementById('totalSnipes').textContent = d.totalSnipes;
    document.getElementById('successRate').textContent = (d.totalSnipes?((d.successful/d.totalSnipes)*100).toFixed(0):0)+'%';
    const pl = document.getElementById('profitLoss');
    pl.textContent = '$'+d.profitLoss.toFixed(2);
    pl.style.color = d.profitLoss>=0?'#10b981':'#ef4444';
});
socket.on('snipe_executed', d => addLog('🚨 '+d.message, 'snipe'));

function addLog(msg, type='info') {
    const log = document.getElementById('activityLog');
    const time = new Date().toTimeString().split(' ')[0];
    log.insertBefore(Object.assign(document.createElement('div'), {
        className: `log-entry ${type}`,
        innerHTML: `<span>${time}</span> <span>${msg}</span>`
    }), log.firstChild);
    while(log.children.length > 50) log.removeChild(log.lastChild);
}

function startTimer() {
    if(timerInterval) clearInterval(timerInterval);
    timerInterval = setInterval(() => {
        if(!marketEndTime) return;
        const remaining = Math.max(0, marketEndTime - Date.now());
        const secs = Math.floor(remaining/1000);
        const mins = Math.floor(secs/60);
        const display = document.getElementById('timerDisplay');
        display.textContent = `${mins.toString().padStart(2,'0')}:${(secs%60).toString().padStart(2,'0')}`;
        display.className = secs<=10?'timer-display critical':'timer-display';
        document.getElementById('timerStatus').textContent = secs<=30?'🔥 Final moments':secs<=60?'⚡ One minute':'Tracking';
        if(secs===0) clearInterval(timerInterval);
    }, 100);
}

function startBot() {
    socket.emit('start_bot');
    document.getElementById('startBtn').disabled = true;
    document.getElementById('stopBtn').disabled = false;
}

function stopBot() {
    socket.emit('stop_bot');
    document.getElementById('startBtn').disabled = false;
    document.getElementById('stopBtn').disabled = true;
    if(timerInterval) clearInterval(timerInterval);
}