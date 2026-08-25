(() => {
  const loader = document.currentScript;
  const appScript = loader?.dataset.app || "model-dashboard.js";
  const manifestPath = loader?.dataset.manifest || "assets/model-manifest.json";

  function loadScript(path, revision) {
    return new Promise((resolve, reject) => {
      const script = document.createElement("script");
      const separator = path.includes("?") ? "&" : "?";
      script.src = `${path}${separator}v=${encodeURIComponent(revision)}`;
      script.onload = resolve;
      script.onerror = () => reject(new Error(`无法加载 ${path}`));
      document.body.appendChild(script);
    });
  }

  async function start() {
    const separator = manifestPath.includes("?") ? "&" : "?";
    const response = await fetch(`${manifestPath}${separator}refresh=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`数据清单请求失败：HTTP ${response.status}`);
    const manifest = await response.json();
    const revision = manifest.revision || Date.now().toString();
    window.MODEL_MANIFEST = manifest;
    await loadScript(manifest.assets?.core || "assets/model-data.js", revision);
    await loadScript(manifest.assets?.extras || "assets/model-extras.js", revision);
    await loadScript(appScript, revision);
  }

  start().catch((error) => {
    const state = document.getElementById("datasetState");
    if (state) state.textContent = `数据加载失败 · ${error.message}`;
    console.error(error);
  });
})();
