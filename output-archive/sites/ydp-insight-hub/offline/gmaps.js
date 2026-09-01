/*
 * 구글 지도 → Leaflet 어댑터 (오프라인 보존용)
 *
 * 원본 대시보드는 구글 지도 API 중 Map · InfoWindow · Polygon · Marker
 * 네 가지만 씁니다. 그만큼만 Leaflet 으로 흉내 내면 앱 코드를 하나도
 * 고치지 않고 지도가 그대로 동작합니다.
 *
 * 배경 지도는 offline-map/tiles/ 에 미리 받아둔 영등포구 범위 타일입니다.
 * 외부로 나가는 요청이 없으므로 인터넷이 끊겨도 동작합니다.
 */
(function () {
  'use strict';

  /* 받아둔 타일 범위. 구 경계(37.485~37.550, 126.879~126.950)에
     화면 가장자리가 비지 않도록 여유를 둔 값이다. */
  var BOUNDS = L.latLngBounds([37.4700, 126.8560], [37.5650, 126.9740]);
  var MIN_ZOOM = 13;
  var MAX_ZOOM = 16;
  var TILE_URL = '/offline/tiles/{z}/{x}/{y}.png';

  /* 받아둔 범위를 벗어난 타일은 빈 칸으로 — 404 를 띄우지 않는다 */
  var BLANK = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"></svg>');

  function toLatLng(p) {
    if (!p) return null;
    if (typeof p.lat === 'function') return L.latLng(p.lat(), p.lng());
    return L.latLng(p.lat, p.lng);
  }

  /* ── Map ─────────────────────────────────────────── */
  function GMap(el, opts) {
    opts = opts || {};
    var map = L.map(el, {
      center: opts.center ? toLatLng(opts.center) : BOUNDS.getCenter(),
      zoom: opts.zoom || MIN_ZOOM,
      minZoom: MIN_ZOOM,
      maxZoom: MAX_ZOOM,
      maxBounds: BOUNDS,
      maxBoundsViscosity: 1,
      zoomControl: opts.zoomControl !== false,
      attributionControl: true
    });

    L.tileLayer(TILE_URL, {
      minZoom: MIN_ZOOM,
      maxZoom: MAX_ZOOM,
      bounds: BOUNDS,
      errorTileUrl: BLANK,
      attribution: '지도 © OpenStreetMap 기여자'
    }).addTo(map);

    this._map = map;

    /* 컨테이너 크기가 나중에 잡히는 경우 대비 */
    var fix = function () { map.invalidateSize(); };
    setTimeout(fix, 0);
    setTimeout(fix, 250);
    if (window.ResizeObserver) {
      var ro = new ResizeObserver(fix);
      ro.observe(el);
    }
  }
  GMap.prototype.getLeaflet = function () { return this._map; };

  /* ── 오버레이 공통 ───────────────────────────────── */
  function bindOverlay(proto) {
    proto.setMap = function (gmap) {
      if (this._layer && this._gmap) this._gmap._map.removeLayer(this._layer);
      this._gmap = gmap || null;
      if (gmap && this._layer) this._layer.addTo(gmap._map);
      return this;
    };
    proto.addListener = function (evt, cb) {
      var self = this;
      if (this._layer) {
        this._layer.on(evt, function (e) {
          cb({ latLng: e.latlng || self._position });
        });
      }
      return this;
    };
  }

  /* ── Polygon ─────────────────────────────────────── */
  function GPolygon(opts) {
    opts = opts || {};
    var ring = (opts.paths || []).map(toLatLng);
    this._layer = L.polygon(ring, {
      color: opts.strokeColor || '#666',
      opacity: opts.strokeOpacity != null ? opts.strokeOpacity : 1,
      weight: opts.strokeWeight != null ? opts.strokeWeight : 1,
      fillColor: opts.fillColor || '#999',
      fillOpacity: opts.fillOpacity != null ? opts.fillOpacity : 0.4,
      interactive: opts.clickable !== false
    });
    this._gmap = null;
    if (opts.map) this.setMap(opts.map);
  }
  bindOverlay(GPolygon.prototype);

  /* ── Marker ──────────────────────────────────────── */
  function GMarker(opts) {
    opts = opts || {};
    var icon = opts.icon || {};
    this._position = toLatLng(opts.position);
    this._layer = L.circleMarker(this._position, {
      radius: icon.scale || 6,
      fillColor: icon.fillColor || '#0d7a6b',
      fillOpacity: icon.fillOpacity != null ? icon.fillOpacity : 0.9,
      color: icon.strokeColor || '#ffffff',
      weight: icon.strokeWeight != null ? icon.strokeWeight : 1.5
    });
    if (opts.title) this._layer.bindTooltip(opts.title);
    this._gmap = null;
    if (opts.map) this.setMap(opts.map);
  }
  bindOverlay(GMarker.prototype);
  GMarker.prototype.getPosition = function () { return this._position; };

  /* ── InfoWindow ──────────────────────────────────── */
  function GInfoWindow() {
    this._popup = L.popup({ maxWidth: 260, autoPan: true });
    this._content = '';
    this._position = null;
  }
  GInfoWindow.prototype.setContent = function (html) {
    this._content = html;
    this._popup.setContent(html);
    return this;
  };
  GInfoWindow.prototype.setPosition = function (p) {
    this._position = toLatLng(p);
    return this;
  };
  GInfoWindow.prototype.open = function (o) {
    o = o || {};
    var gmap = o.map;
    var pos = this._position;
    if (o.anchor && o.anchor.getPosition) pos = o.anchor.getPosition();
    if (!gmap || !pos) return this;
    this._popup.setLatLng(pos).setContent(this._content).openOn(gmap._map);
    return this;
  };
  GInfoWindow.prototype.close = function () {
    this._popup.close();
    return this;
  };

  /* ── 앱이 기대하는 모양으로 노출 ─────────────────── */
  window.google = window.google || {};
  window.google.maps = {
    Map: GMap,
    InfoWindow: GInfoWindow,
    Polygon: GPolygon,
    Marker: GMarker,
    SymbolPath: { CIRCLE: 'circle' }
  };
})();
