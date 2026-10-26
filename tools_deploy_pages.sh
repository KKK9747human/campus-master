#!/usr/bin/env bash
# ============================================================
# 部署 web/ 到 gh-pages 分支（GitHub Pages 静态镜像）
# Pages 是项目子路径（/campus-master/），页面里的 /web/ 绝对路径
# 全部改成相对路径；镜像分支为纯静态，不包含任何后端代码
# 用法: bash tools_deploy_pages.sh   （改完 web/ 后跑一次即可）
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

git worktree add _pages_out gh-pages 2>/dev/null || true

# 同步 web/ 静态文件到镜像（不留旧文件，防残留已删页面）
find _pages_out -maxdepth 1 -type f ! -name .git -delete
cp web/*.html web/*.css web/*.js _pages_out/

# /web/xxx → xxx（Pages 扁平根目录下的相对引用）
sed -i 's|/web/||g' _pages_out/*.html
# 品牌 logo 的 href="/" 在 Pages 会跳到 github.io 根路径，改回首页
sed -i 's|class="brand" href="/"|class="brand" href="index.html"|' _pages_out/*.html
# Pages 上没有 /docs（后端 Swagger），撤掉首页这个入口（不锁按钮文案）
sed -i -E 's|<a class="btn btn-ghost" href="/docs"[^>]*>[^<]*</a>||' _pages_out/index.html

cd _pages_out
git add -A
if git diff --cached --quiet; then
  echo "gh-pages 已是最新，无需部署"
else
  git commit -m "deploy: sync web/ -> gh-pages ($(date +%F\ %H:%M))"
  git push origin gh-pages
  echo "已推送 gh-pages，Pages 构建约 1-2 分钟后生效"
fi
cd ..
git worktree remove _pages_out
