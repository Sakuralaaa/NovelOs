#!/usr/bin/env bash
# NovelOS 一键部署：bash deploy.sh
# 1) 检查 docker / docker compose  2) 缺 .env 时自动生成  3) 构建并启动  4) 等待健康检查通过并打印访问地址
set -euo pipefail
cd "$(dirname "$0")"

say()  { printf '\033[1;32m[NovelOS]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[NovelOS]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[NovelOS]\033[0m %s\n' "$*" >&2; exit 1; }

# ---------- 1. 环境检查 ----------
if ! command -v docker >/dev/null 2>&1; then
  cat >&2 <<'TIP'
[NovelOS] 没有找到 docker。请先安装：
  · Ubuntu / Debian / CentOS 服务器：curl -fsSL https://get.docker.com | sudo sh
      （国内网络可加镜像：curl -fsSL https://get.docker.com | sudo sh -s -- --mirror Aliyun）
      安装后执行：sudo systemctl enable --now docker
  · Windows / macOS：安装 Docker Desktop（https://www.docker.com/products/docker-desktop/），启动后再运行本脚本
TIP
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  die "没有找到 docker compose 插件。Ubuntu/Debian：sudo apt-get install -y docker-compose-plugin；其他系统请升级 Docker 到 20.10 以上或安装 Docker Desktop。"
fi

if ! docker info >/dev/null 2>&1; then
  die "Docker 没有运行，或当前用户没有权限。请先启动 Docker（sudo systemctl start docker），或用 sudo bash deploy.sh 运行，或把当前用户加入 docker 组：sudo usermod -aG docker \$USER 后重新登录。"
fi

# ---------- 2. 配置 ----------
gen_secret() {
  if command -v openssl >/dev/null 2>&1; then openssl rand -hex 32
  elif command -v python3 >/dev/null 2>&1; then python3 -c 'import secrets; print(secrets.token_hex(32))'
  else head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'; fi
}

if [ ! -f .env ]; then
  [ -f .env.example ] || die "缺少 .env.example，请确认代码完整"
  cp .env.example .env
  secret="$(gen_secret)"
  if grep -q '^NOVELOS_SECRET=' .env; then
    sed -i.bak "s/^NOVELOS_SECRET=.*/NOVELOS_SECRET=${secret}/" .env && rm -f .env.bak
  else
    echo "NOVELOS_SECRET=${secret}" >> .env
  fi
  say "已生成 .env（含随机 NOVELOS_SECRET）。请妥善保管，丢失后已保存的模型 Key 需要重新填写。"
elif ! grep -q '^NOVELOS_SECRET=.\+' .env; then
  warn ".env 里 NOVELOS_SECRET 为空：将使用 ./data/secret.key 中自动生成的密钥（也可以）。"
fi

APP_PORT="$(grep -E '^APP_PORT=' .env | tail -1 | cut -d= -f2 | tr -d ' "\r')"
APP_PORT="${APP_PORT:-8080}"
mkdir -p data

# ---------- 3. 构建并启动 ----------
say "开始构建并启动（首次构建需要下载依赖，约 3–10 分钟）……"
"${COMPOSE[@]}" up -d --build

# ---------- 4. 等待就绪 ----------
say "等待服务就绪（http://127.0.0.1:${APP_PORT}/api/health）……"
ok=0
for _ in $(seq 1 90); do
  if command -v curl >/dev/null 2>&1; then
    curl -fsS "http://127.0.0.1:${APP_PORT}/api/health" >/dev/null 2>&1 && ok=1 && break
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- "http://127.0.0.1:${APP_PORT}/api/health" >/dev/null 2>&1 && ok=1 && break
  else
    docker exec novelos python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)" >/dev/null 2>&1 && ok=1 && break
  fi
  sleep 2
done

if [ "$ok" != 1 ]; then
  warn "180 秒内没有等到健康检查通过。最近日志："
  "${COMPOSE[@]}" logs --tail=60 novelos || true
  die "启动失败。常见原因：端口 ${APP_PORT} 被占用（改 .env 里的 APP_PORT 后重跑），或构建时网络不通。"
fi

LAN_IP="$( (hostname -I 2>/dev/null || true) | awk '{print $1}')"
say "部署完成！"
echo "  本机访问：   http://127.0.0.1:${APP_PORT}"
[ -n "${LAN_IP}" ] && echo "  局域网访问： http://${LAN_IP}:${APP_PORT}"
echo "  第一次打开请进入“设置”页填写模型渠道（OpenAI 兼容 base_url + Key）；不填也能用演示（mock）模式体验全流程。"
echo "  查看日志：${COMPOSE[*]} logs -f novelos    停止：${COMPOSE[*]} down"
