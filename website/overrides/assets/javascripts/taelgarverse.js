(function () {
  "use strict";

  var leafletUrl = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
  var leafletIntegrity = "sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=";
  var leafletPromise = null;
  var observerStarted = false;
  var scanQueued = false;

  function loadLeaflet() {
    if (window.L && window.L.map) {
      return Promise.resolve(window.L);
    }
    if (leafletPromise) {
      return leafletPromise;
    }
    leafletPromise = new Promise(function (resolve, reject) {
      var script = document.querySelector('script[src="' + leafletUrl + '"]');
      if (!script) {
        script = document.createElement("script");
        script.src = leafletUrl;
        script.integrity = leafletIntegrity;
        script.crossOrigin = "";
        document.head.appendChild(script);
      }

      function waitForLeaflet(remainingAttempts) {
        if (window.L && window.L.map) {
          resolve(window.L);
          return;
        }
        if (remainingAttempts <= 0) {
          reject(new Error("Leaflet did not load"));
          return;
        }
        window.setTimeout(function () {
          waitForLeaflet(remainingAttempts - 1);
        }, 50);
      }

      script.addEventListener("error", function () {
        reject(new Error("Unable to load Leaflet"));
      }, { once: true });
      waitForLeaflet(120);
    });
    return leafletPromise;
  }

  function initMaps() {
    document.querySelectorAll(".taelgar-leaflet-map[data-taelgar-leaflet]").forEach(initMap);
  }

  function initMap(container) {
    if (container.dataset.taelgarLeafletInitialized === "true") {
      return;
    }
    var config;
    try {
      config = JSON.parse(container.dataset.taelgarLeaflet || "{}");
    } catch (error) {
      console.error("Invalid Taelgar map config", error);
      return;
    }
    if (!config.bounds || (!config.tile && !config.image)) {
      return;
    }

    loadLeaflet().then(function () {
      if (!document.body.contains(container) || container.dataset.taelgarLeafletInitialized === "true") {
        return;
      }
      container.dataset.taelgarLeafletInitialized = "true";
      container.innerHTML = "";

      var map = L.map(container, {
        crs: L.CRS.Simple,
        minZoom: config.minZoom,
        maxZoom: config.maxZoom
      });
      var imageBounds = L.latLngBounds(config.bounds);

      if (config.tile) {
        addTileLayer(map, imageBounds, config.tile);
        map.setMaxBounds(imageBounds.pad(0.05));
      } else {
        L.imageOverlay(config.image.url, imageBounds).addTo(map);
      }

      if (config.fitBounds || !config.center) {
        map.fitBounds(imageBounds);
      } else {
        map.setView(config.center, config.defaultZoom);
      }
      window.setTimeout(function () {
        map.invalidateSize();
      }, 0);
    }).catch(function (error) {
      console.error("Unable to initialize Taelgar map", error);
    });
  }

  function addTileLayer(map, imageBounds, tileConfig) {
    var blankTile = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==";
    var tileSize = tileConfig.tileSize || 512;
    var minNativeZoom = tileConfig.minNativeZoom || 0;
    var maxNativeZoom = tileConfig.maxNativeZoom || 0;
    var baseUrl = tileConfig.baseUrl;
    var cacheKey = tileConfig.cacheKey;
    var extension = tileConfig.extension || "webp";
    var width = tileConfig.width;
    var height = tileConfig.height;

    var TaelgarTileLayer = L.TileLayer.extend({
      getTileUrl: function (coords) {
        var zoom = Math.max(minNativeZoom, Math.min(maxNativeZoom, coords.z));
        var scale = Math.pow(2, zoom);
        var xCount = Math.ceil(width * scale / tileSize);
        var yCount = Math.ceil(height * scale / tileSize);
        var col = coords.x;
        var row = coords.y + yCount;
        if (col < 0 || col >= xCount || row < 0 || row >= yCount) {
          return blankTile;
        }
        var url = baseUrl + "/" + zoom + "/" + col + "/" + row + "." + extension;
        if (cacheKey) {
          url += "?v=" + encodeURIComponent(cacheKey);
        }
        return url;
      }
    });

    new TaelgarTileLayer("", {
      tileSize: tileSize,
      minZoom: map.getMinZoom(),
      maxZoom: map.getMaxZoom(),
      minNativeZoom: minNativeZoom,
      maxNativeZoom: maxNativeZoom,
      noWrap: true,
      bounds: imageBounds
    }).addTo(map);
  }

  function queueScan() {
    if (scanQueued) {
      return;
    }
    scanQueued = true;
    window.requestAnimationFrame(function () {
      scanQueued = false;
      initMaps();
    });
  }

  function start() {
    initMaps();
    if (observerStarted) {
      return;
    }
    observerStarted = true;
    new MutationObserver(queueScan).observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
