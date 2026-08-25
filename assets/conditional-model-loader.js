(() => {
  const loader = document.currentScript;
  const manifestPath = loader?.dataset.manifest || "assets/model-manifest.json";
  const appScript = loader?.dataset.app || "conditional-model-app.js";

  function loadScript(path, revision) {
    return new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = `${path}${path.includes("?") ? "&" : "?"}v=${encodeURIComponent(revision)}`;
      script.onload = resolve;
      script.onerror = () => reject(new Error(`无法加载 ${path}`));
      document.body.appendChild(script);
    });
  }

  async function start() {
    const response = await fetch(`${manifestPath}${manifestPath.includes("?") ? "&" : "?"}refresh=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`数据清单请求失败：HTTP ${response.status}`);
    const manifest = await response.json();
    const revision = manifest.revision || Date.now().toString();
    window.MODEL_MANIFEST = manifest;
    await loadScript(manifest.assets?.conditional || "assets/conditional-model.js", revision);
    await loadScript(manifest.assets?.playerCase || "assets/player-case.js", revision);
    await loadScript(appScript, revision);
  }

  start().catch((error) => {
    const state = document.getElementById("modelLoadState");
    if (state) state.textContent = `模型加载失败 · ${error.message}`;
    console.error(error);
  });
})();
