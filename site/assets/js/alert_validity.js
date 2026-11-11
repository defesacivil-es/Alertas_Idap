(function () {
  function timestamp(value) {
    if (!value) return NaN;
    return Date.parse(value);
  }

  function isActive(alert, now = Date.now()) {
    const start = timestamp(alert.onset || alert.sent);
    const end = timestamp(alert.expires);
    return Number.isFinite(end) && now < end && (!Number.isFinite(start) || start <= now);
  }

  // Recheck locally, even when the published files or network are unavailable.
  function watch(collection, render) {
    const features = Array.isArray(collection?.features) ? collection.features : [];
    let previous = null;
    function update() {
      const now = Date.now();
      const active = features.filter((feature) => isActive(feature.properties || {}, now));
      if (previous && active.length === previous.length && active.every((feature, i) => feature === previous[i])) return;
      previous = active;
      const ids = new Set(active.map((feature) => feature.properties?.identifier || feature.properties?.entry_id || feature));
      render({ ...collection, type: 'FeatureCollection', features: active, total_alerts: ids.size });
    }
    update();
    const timer = setInterval(update, 1000);
    document.addEventListener('visibilitychange', update);
    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', update);
    };
  }

  window.AlertValidity = { isActive, watch };
})();
