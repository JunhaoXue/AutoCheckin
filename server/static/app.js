// --- WebSocket connection ---
let ws = null;
let reconnectTimer = null;
const WS_URL = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/dashboard`;

function connectWS() {
    if (ws && ws.readyState <= 1) return;
    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
        addLog('WebSocket 已连接', 'info');
        if (reconnectTimer) clearInterval(reconnectTimer);
        // Keep-alive ping
        setInterval(() => {
            if (ws.readyState === 1) ws.send(JSON.stringify({type: 'ping'}));
        }, 25000);
    };

    ws.onmessage = (e) => {
        try {
            const msg = JSON.parse(e.data);
            handleWSMessage(msg);
        } catch (err) {
            console.error('WS parse error:', err);
        }
    };

    ws.onclose = () => {
        addLog('WebSocket 断开，5秒后重连...', 'error');
        reconnectTimer = setTimeout(connectWS, 5000);
    };

    ws.onerror = () => {
        ws.close();
    };
}

function handleWSMessage(msg) {
    switch (msg.type) {
        case 'init_state':
            updateConnectionStatus(msg.data.phone_online);
            if (msg.data.device_status) updateDeviceInfo(msg.data.device_status);
            if (msg.data.today_checkins) updateTodayCheckins(msg.data.today_checkins);
            break;
        case 'connection_status':
            updateConnectionStatus(msg.data.phone_online);
            addLog(msg.data.phone_online ? '手机已连接' : '手机已断开', msg.data.phone_online ? 'success' : 'error');
            break;
        case 'device_update':
            updateConnectionStatus(true);
            updateDeviceInfo(msg.data);
            break;
        case 'checkin_update':
            handleCheckinUpdate(msg.data);
            break;
        case 'screenshot_update':
            showScreenshot(msg.data.screenshot_path);
            break;
        case 'error_update':
            addLog(`错误: ${msg.data.error_code} - ${msg.data.message}`, 'error');
            break;
        case 'pong':
            break;
    }
}

// --- UI Updates ---

function updateConnectionStatus(online) {
    const badge = document.getElementById('connection-status');
    const text = document.getElementById('conn-text');
    badge.className = 'status-badge ' + (online ? 'online' : 'offline');
    text.textContent = online ? '手机在线' : '手机离线';
}

function updateDeviceInfo(data) {
    setText('battery', data.battery_level != null ? `${data.battery_level}%${data.battery_charging ? ' ⚡' : ''}` : '--');
    setText('wifi-ssid', data.wifi_ssid || '--');
    setText('wifi-ip', data.wifi_ip || '--');
    setText('adb-status', data.adb_connected ? '已连接' : '未连接');
    if (data.last_heartbeat) {
        const t = new Date(data.last_heartbeat);
        setText('last-heartbeat', t.toLocaleTimeString('zh-CN'));
    }
}

function updateTodayCheckins(checkins) {
    // Morning
    const m = checkins.morning;
    const mIcon = document.getElementById('morning-icon');
    const mTime = document.getElementById('morning-time');
    if (m && m.done) {
        mIcon.textContent = '✓';
        mIcon.className = 'checkin-icon success';
        mTime.textContent = m.time || '已打卡';
    } else {
        mIcon.textContent = '?';
        mIcon.className = 'checkin-icon';
        mTime.textContent = '未打卡';
    }

    // Evening
    const ev = checkins.evening;
    const eIcon = document.getElementById('evening-icon');
    const eTime = document.getElementById('evening-time');
    if (ev && ev.done) {
        eIcon.textContent = '✓';
        eIcon.className = 'checkin-icon success';
        eTime.textContent = ev.time || '已打卡';
    } else {
        eIcon.textContent = '?';
        eIcon.className = 'checkin-icon';
        eTime.textContent = '未打卡';
    }
}

function handleCheckinUpdate(data) {
    const success = data.success;
    const type = data.checkin_type || '';
    const time = data.checkin_time || '';
    const message = data.message || '';

    addLog(`${type}打卡: ${success ? '成功' : '失败'} ${time} ${message}`, success ? 'success' : 'error');

    if (data.today_checkins) {
        updateTodayCheckins(data.today_checkins);
    }

    if (data.screenshot_path) {
        showScreenshot(data.screenshot_path);
    }

    // Refresh history
    loadHistory();
    showActionMsg(success ? `${type}打卡成功 ${time}` : `${type}打卡失败: ${message}`);
}

function showScreenshot(path) {
    if (!path) return;
    const card = document.getElementById('screenshot-card');
    const img = document.getElementById('screenshot-img');
    const timeEl = document.getElementById('screenshot-time');
    card.style.display = 'block';
    img.src = path + '?t=' + Date.now();
    timeEl.textContent = new Date().toLocaleString('zh-CN');
}

function showActionMsg(text) {
    const el = document.getElementById('action-msg');
    el.textContent = text;
    setTimeout(() => { el.textContent = ''; }, 5000);
}

// --- Actions ---

async function triggerCheckin(type) {
    showActionMsg('正在发送打卡命令...');
    try {
        const res = await fetch('/api/checkin', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({checkin_type: type})
        });
        const data = await res.json();
        if (res.ok) {
            showActionMsg(data.message);
            addLog(`手动触发${type}打卡`, 'info');
        } else {
            showActionMsg(data.error || '操作失败');
            addLog(`打卡命令失败: ${data.error}`, 'error');
        }
    } catch (e) {
        showActionMsg('网络错误');
    }
}

async function requestScreenshot() {
    showActionMsg('正在请求截图...');
    try {
        const res = await fetch('/api/screenshot', {method: 'POST'});
        const data = await res.json();
        if (res.ok) {
            showActionMsg('截图命令已发送，等待返回...');
            addLog('请求截图', 'info');
        } else {
            showActionMsg(data.error || '操作失败');
        }
    } catch (e) {
        showActionMsg('网络错误');
    }
}

async function saveSchedule() {
    const config = {
        morning_time: document.getElementById('cfg-morning').value,
        evening_time: document.getElementById('cfg-evening').value,
        random_delay_max: parseInt(document.getElementById('cfg-delay').value) || 900,
        skip_weekends: document.getElementById('cfg-weekends').checked,
        skip_holidays: document.getElementById('cfg-holidays').checked,
    };
    try {
        const res = await fetch('/api/schedule', {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(config)
        });
        const data = await res.json();
        showActionMsg(data.message || '已保存');
        addLog('更新打卡配置', 'info');
    } catch (e) {
        showActionMsg('网络错误');
    }
}

async function loadHistory() {
    const days = document.getElementById('history-days').value;
    try {
        const res = await fetch(`/api/history?days=${days}`);
        const data = await res.json();
        const tbody = document.getElementById('history-body');
        tbody.innerHTML = '';
        (data.logs || []).forEach(log => {
            const tr = document.createElement('tr');
            const successTag = log.success
                ? '<span class="tag tag-success">成功</span>'
                : '<span class="tag tag-fail">失败</span>';
            tr.innerHTML = `
                <td>${formatTime(log.checkin_time)}</td>
                <td>${log.checkin_type}</td>
                <td>${successTag}</td>
                <td>${log.trigger}</td>
                <td>${log.message || '-'}</td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error('Load history error:', e);
    }
}

async function loadSchedule() {
    try {
        const res = await fetch('/api/schedule');
        const data = await res.json();
        if (data.morning_time) document.getElementById('cfg-morning').value = data.morning_time;
        if (data.evening_time) document.getElementById('cfg-evening').value = data.evening_time;
        if (data.random_delay_max != null) document.getElementById('cfg-delay').value = data.random_delay_max;
        document.getElementById('cfg-weekends').checked = !!data.skip_weekends;
        document.getElementById('cfg-holidays').checked = !!data.skip_holidays;
    } catch (e) {
        console.error('Load schedule error:', e);
    }
}

// --- Helpers ---

function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

function formatTime(isoStr) {
    if (!isoStr) return '--';
    try {
        const d = new Date(isoStr);
        return `${(d.getMonth()+1).toString().padStart(2,'0')}-${d.getDate().toString().padStart(2,'0')} ${d.toLocaleTimeString('zh-CN')}`;
    } catch {
        return isoStr;
    }
}

function addLog(text, level = 'info') {
    const area = document.getElementById('log-area');
    const line = document.createElement('div');
    line.className = 'log-line';
    const now = new Date().toLocaleTimeString('zh-CN');
    line.innerHTML = `<span class="log-time">[${now}]</span> <span class="log-${level}">${escapeHtml(text)}</span>`;
    area.appendChild(line);
    area.scrollTop = area.scrollHeight;
    // Keep max 200 lines
    while (area.children.length > 200) area.removeChild(area.firstChild);
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// --- Init ---
document.addEventListener('DOMContentLoaded', () => {
    connectWS();
    loadSchedule();
    loadHistory();
    addLog('Dashboard 已加载', 'info');
});
