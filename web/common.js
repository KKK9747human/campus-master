/* =====================================================
   掌控校园 · 全站共享脚本：手写记号
   给 [data-ring] 元素（各页标题）叠一支朱笔圈——
   圈阅 = 中式批阅动作，选定、圆满；动画节奏在 common.css
   ===================================================== */
(function () {
  const RING_PATH = "M 30 26 C 78 10, 180 2, 246 10 C 292 16, 314 36, 304 58 "
    + "C 292 80, 214 94, 128 92 C 56 90, 12 74, 10 52 C 8 34, 36 20, 86 12";
  const TAIL_PATH = "M 96 10 C 70 12, 48 17, 28 27";   // 主圈闭合后的补笔小尾巴

  function ringOne(el) {
    if (el.dataset.ringed) return;
    el.dataset.ringed = "1";
    el.classList.add("ringed");
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "title-ring");
    svg.setAttribute("viewBox", "0 0 320 96");
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("aria-hidden", "true");
    const main = document.createElementNS("http://www.w3.org/2000/svg", "path");
    main.setAttribute("pathLength", "100");
    main.setAttribute("vector-effect", "non-scaling-stroke");
    main.setAttribute("d", RING_PATH);
    svg.appendChild(main);
    const tail = document.createElementNS("http://www.w3.org/2000/svg", "path");
    tail.setAttribute("class", "tail");
    tail.setAttribute("pathLength", "100");
    tail.setAttribute("vector-effect", "non-scaling-stroke");
    tail.setAttribute("d", TAIL_PATH);
    svg.appendChild(tail);
    el.appendChild(svg);
  }

  const init = () => document.querySelectorAll("[data-ring]").forEach(ringOne);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

/* =====================================================
   GitHub Pages 静态镜像提示：Pages 上没有后端，接口全部不在线。
   仅在 *.github.io 域名下出现，本地/云上部署不受影响
   ===================================================== */
(function () {
  if (!location.hostname.endsWith("github.io")) return;
  const bar = document.createElement("div");
  bar.style.cssText = "position:fixed;left:0;right:0;bottom:0;z-index:50;"
    + "background:#211F1A;color:#F6F3EA;font-size:12px;text-align:center;"
    + "padding:7px 12px;letter-spacing:.04em";
  bar.innerHTML = "Static demo on GitHub Pages — 后端接口不在线，仅可浏览界面与排版；完整体验请本地运行（见仓库 DEPLOY.md）";
  document.body.appendChild(bar);
  document.body.style.paddingBottom = "32px";
})();
