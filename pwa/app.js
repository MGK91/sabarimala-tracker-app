const app = {
  data: null,
  refreshInterval: null,
  map: null,
  markers: {},
  routePolyline: null,

  init() {
    this.registerSW();
    this.loadData();
    this.refreshInterval = setInterval(() => this.loadData(), 60000);
    this.updateConnectionStatus();
    window.addEventListener('online', () => this.updateConnectionStatus());
    window.addEventListener('offline', () => this.updateConnectionStatus());
    this.requestNotificationPermission();
  },

  registerSW() {
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('sw.js')
        .then(() => console.log('SW registered'))
        .catch(err => console.error('SW failed', err));
    }
  },

  updateConnectionStatus() {
    const el = document.getElementById('conn-status');
    if (navigator.onLine) {
      el.innerHTML = '<span class="status-dot"></span>Live';
      el.querySelector('.status-dot').classList.remove('offline');
    } else {
      el.innerHTML = '<span class="status-dot offline"></span>Offline';
    }
  },

  switchTab(tab) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    document.getElementById('tab-' + tab).classList.add('active');
    document.getElementById('panel-' + tab).classList.add('active');
    if (tab === 'map') {
      setTimeout(() => this.initMap(), 50);
    }
  },

  async loadData() {
    try {
      const res = await fetch(`data.json?_=${Date.now()}`);
      if (!res.ok) throw new Error('HTTP ' + res.status);
      this.data = await res.json();
      this.render();
    } catch (e) {
      console.error('Failed to load data', e);
      if (!this.data) {
        try {
          const cache = await caches.match('data.json');
          if (cache) {
            this.data = await cache.json();
            this.render();
          }
        } catch (e2) {}
      }
    }
  },

  refresh() {
    this.loadData();
  },

  render() {
    if (!this.data) return;
    this.renderDistricts();
    this.renderRoute();
    this.renderAlerts();
    if (document.getElementById('panel-map').classList.contains('active')) {
      this.updateMapMarkers();
    }
  },

  renderDistricts() {
    const container = document.getElementById('districts');
    const districts = this.data.districts || {};
    const thresholds = { daily: 115, threeDay: 200, sevenDay: 350 };

    container.innerHTML = Object.entries(districts).map(([name, d]) => {
      const level = d.level || 'green';
      const rain24 = d.rainfall_24h || 0;
      const rain3d = d.rainfall_3d || 0;
      const rain7d = d.rainfall_7d || 0;
      const landslide = d.landslide_risk || 'low';
      const pct24 = Math.min((rain24 / thresholds.daily) * 100, 100);
      const pct3d = Math.min((rain3d / thresholds.threeDay) * 100, 100);
      const pct7d = Math.min((rain7d / thresholds.sevenDay) * 100, 100);

      const lsClass = landslide === 'high' ? 'high' : landslide === 'moderate' ? 'moderate' : '';

      return `
        <div class="district-card ${level}">
          <div class="district-header">
            <span class="district-name">${name}</span>
            <div>
              <span class="badge ${level}">${level}</span>
              <span class="landslide-badge ${lsClass}">🌋 ${landslide}</span>
            </div>
          </div>
          <div class="rainfall-row">
            <div class="rainfall-item">
              <div class="rainfall-value" style="color:var(--${pct24 > 100 ? 'red' : pct24 > 70 ? 'orange' : 'green'})">${rain24.toFixed(1)}</div>
              <div class="rainfall-label">24h mm</div>
              <div class="threshold-bar"><div class="threshold-fill ${pct24 > 100 ? 'red' : pct24 > 70 ? 'orange' : ''}" style="width:${pct24}%"></div></div>
            </div>
            <div class="rainfall-item">
              <div class="rainfall-value" style="color:var(--${pct3d > 100 ? 'red' : pct3d > 70 ? 'orange' : 'green'})">${rain3d.toFixed(1)}</div>
              <div class="rainfall-label">3-day mm</div>
              <div class="threshold-bar"><div class="threshold-fill ${pct3d > 100 ? 'red' : pct3d > 70 ? 'orange' : ''}" style="width:${pct3d}%"></div></div>
            </div>
            <div class="rainfall-item">
              <div class="rainfall-value" style="color:var(--${pct7d > 100 ? 'red' : pct7d > 70 ? 'orange' : 'green'})">${rain7d.toFixed(1)}</div>
              <div class="rainfall-label">7-day mm</div>
              <div class="threshold-bar"><div class="threshold-fill ${pct7d > 100 ? 'red' : pct7d > 70 ? 'orange' : ''}" style="width:${pct7d}%"></div></div>
            </div>
          </div>
          ${d.alert_text ? `<div class="alert-text">⚠ ${d.alert_text}</div>` : ''}
          <div style="margin-top:0.5rem;font-size:0.65rem;color:var(--muted);">
            Sources: ${(d.sources || []).join(', ') || 'None'}
            ${d.since ? '· ' + this.timeAgo(d.since) : ''}
          </div>
        </div>
      `;
    }).join('');
  },

  renderRoute() {
    const container = document.getElementById('route-points');
    const points = this.data.route_points || {};
    const districts = this.data.districts || {};
    const thresholds = { daily: 115 };

    // Order: Chennai → Theni → Kumily → Vandiperiyar → Gavi → Erumely → Pamba → Temple
    const order = ["Chennai", "Theni", "Bodinayakanur", "Kumily", "Vandiperiyar", "Gavi Pass", "Erumely", "Pamba", "Sabarimala Temple"];

    container.innerHTML = order.map(name => {
      const pt = points[name];
      if (!pt) return '';
      const distState = districts[pt.district] || { level: 'green' };
      const level = distState.level;
      const rain24 = pt.rainfall_24h || 0;
      const pct = Math.min((rain24 / thresholds.daily) * 100, 100);

      const icons = {
        city: '🏙️', town: '🏘️', base: '🏕️', temple: '🛕', pass: '🏔️', river: '🌊'
      };
      const icon = icons[pt.type] || '📍';

      return `
        <div class="route-item ${level}">
          <div class="route-icon">${icon}</div>
          <div class="route-info">
            <div class="route-name">${name}</div>
            <div class="route-meta">${pt.district}, ${pt.state} · ${pt.type}</div>
          </div>
          <div class="route-rain">
            <div class="route-rain-val" style="color:var(--${pct > 100 ? 'red' : pct > 70 ? 'orange' : 'green'})">${rain24.toFixed(1)}</div>
            <div class="route-rain-label">24h mm</div>
          </div>
        </div>
      `;
    }).join('');
  },

  renderAlerts() {
    const container = document.getElementById('alerts-list');
    const alerts = (this.data.latest_alerts || []).slice(0, 30);

    if (alerts.length === 0) {
      container.innerHTML = '<div class="empty-state">No active alerts</div>';
      return;
    }

    container.innerHTML = alerts.map(a => {
      const sev = a.severity || 'green';
      const time = a.timestamp ? this.timeAgo(a.timestamp) : 'Just now';
      return `
        <div class="alert-item ${sev}">
          <div class="alert-meta">
            <span class="alert-source">${a.source}</span>
            <span class="alert-time">${time}</span>
          </div>
          <div class="alert-title">${a.title}</div>
          <div class="alert-body">${a.body}</div>
        </div>
      `;
    }).join('');
  },

  // ======================== MAP ========================
  initMap() {
    if (this.map) {
      this.updateMapMarkers();
      return;
    }

    this.map = L.map('map').setView([9.8, 77.2], 8);

    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      attribution: '&copy; OSM &copy; CARTO',
      subdomains: 'abcd',
      maxZoom: 19
    }).addTo(this.map);

    this.updateMapMarkers();
  },

  updateMapMarkers() {
    if (!this.map || !this.data) return;

    Object.values(this.markers).forEach(m => this.map.removeLayer(m));
    this.markers = {};
    if (this.routePolyline) {
      this.map.removeLayer(this.routePolyline);
    }

    const districts = this.data.districts || {};
    const points = this.data.route_points || {};

    // Route order for polyline
    const routeOrder = ["Chennai", "Theni", "Bodinayakanur", "Kumily", "Vandiperiyar", "Gavi Pass", "Erumely", "Pamba", "Sabarimala Temple"];
    const routeCoords = [];

    routeOrder.forEach(name => {
      const pt = points[name];
      if (!pt) return;
      routeCoords.push([pt.lat, pt.lon]);

      const distState = districts[pt.district] || { level: 'green' };
      const level = distState.level;
      const colors = { green: '#22c55e', orange: '#f59e0b', red: '#ef4444' };
      const color = colors[level] || colors.green;

      let iconHtml;
      if (pt.type === 'temple') {
        iconHtml = `<div style="font-size:24px;text-align:center;filter:drop-shadow(0 0 4px ${color});">🛕</div>`;
      } else if (pt.type === 'pass') {
        iconHtml = `<div style="font-size:20px;text-align:center;filter:drop-shadow(0 0 4px ${color});">🏔️</div>`;
      } else if (pt.type === 'base') {
        iconHtml = `<div style="font-size:20px;text-align:center;filter:drop-shadow(0 0 4px ${color});">🏕️</div>`;
      } else if (pt.type === 'city') {
        iconHtml = `<div style="width:16px;height:16px;background:${color};border-radius:50%;border:2px solid #fff;box-shadow:0 0 8px ${color};"></div>`;
      } else {
        iconHtml = `<div style="width:12px;height:12px;background:${color};border-radius:50%;border:2px solid #fff;box-shadow:0 0 6px ${color};"></div>`;
      }

      const icon = L.divIcon({
        className: 'custom-marker',
        html: iconHtml,
        iconSize: pt.type === 'temple' ? [32, 32] : pt.type === 'city' ? [22, 22] : [18, 18],
        iconAnchor: pt.type === 'temple' ? [16, 16] : pt.type === 'city' ? [11, 11] : [9, 9]
      });

      const popupContent = `
        <b>${name}</b><br>
        <span style="color:${color};font-weight:700;">${level.toUpperCase()}</span> · ${pt.district}<br>
        24h: ${pt.rainfall_24h?.toFixed(1) || 0} mm<br>
        3-day: ${pt.rainfall_3d?.toFixed(1) || 0} mm<br>
        7-day: ${pt.rainfall_7d?.toFixed(1) || 0} mm
      `;

      const marker = L.marker([pt.lat, pt.lon], { icon }).addTo(this.map);
      marker.bindPopup(popupContent);
      this.markers[name] = marker;
    });

    // Draw route polyline
    if (routeCoords.length > 1) {
      this.routePolyline = L.polyline(routeCoords, {
        color: '#f59e0b',
        weight: 3,
        opacity: 0.5,
        dashArray: '10, 8'
      }).addTo(this.map);
    }

    // Fit bounds if first load
    if (routeCoords.length > 1 && !this._mapFitted) {
      this.map.fitBounds(routeCoords, { padding: [40, 40] });
      this._mapFitted = true;
    }
  },

  timeAgo(iso) {
    const then = new Date(iso);
    const now = new Date();
    const secs = Math.floor((now - then) / 1000);
    if (secs < 60) return 'Just now';
    const mins = Math.floor(secs / 60);
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.floor(hrs / 24)}d ago`;
  },

  requestNotificationPermission() {
    if ('Notification' in window && Notification.permission === 'default') {
      setTimeout(() => {
        if (confirm('Enable push notifications for risk alerts?')) {
          Notification.requestPermission().then(perm => {
            if (perm === 'granted') {
              new Notification('Sabarimala Route Risk Monitor', {
                body: 'You will receive alerts when risk levels change.',
                icon: 'data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 192 192'%3E%3Crect fill='%230f172a' width='192' height='192' rx='24'/%3E%3Ctext x='96' y='120' font-size='80' text-anchor='middle' fill='%23f59e0b'%3E🛕%3C/text%3E%3C/svg%3E'
              });
            }
          });
        }
      }, 2000);
    }
  }
};

document.addEventListener('DOMContentLoaded', () => app.init());
