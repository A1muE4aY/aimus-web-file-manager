#!/usr/bin/env bash
# AWFM WSL 测试床（决策 D-012）：在 WSL 里以**普通用户**跑一个非 root 的 sshd，
# 给 tests/integration 提供一个真实的 SSH/SFTP 目标机 —— 不需要 sudo，不碰任何系统目录。
#
# 用法（在项目根目录，Windows 侧直接调 wsl）：
#   wsl -d Ubuntu bash scripts/testbed_wsl.sh up       # 幂等：该建的建、该启的启，已就绪就什么都不做
#   wsl -d Ubuntu bash scripts/testbed_wsl.sh status   # 看状态（端口 / PID / 指纹 / 日志）
#   wsl -d Ubuntu bash scripts/testbed_wsl.sh stop     # 停止（按 pidfile，必要时按端口兜底）
#
# 目录布局（全部在 ~/.awfm-testbed 下）：
#   deb/                         apt-get download 下来的 openssh-server .deb（只下载不安装）
#   root/                        dpkg -x 解包结果：root/usr/sbin/sshd、root/usr/lib/openssh/sftp-server
#   keys/id_ed25519[.pub]        测试床自己的客户端密钥（600 / 644）
#   sshd/etc/sshd_config         见下方 write_sshd_config（端口 2222，只监听 127.0.0.1）
#   sshd/etc/ssh_host_ed25519_key 主机密钥（600）
#   sshd/home/authorized_keys    0700 目录 + 0600 文件；写入测试床密钥与仓库里的 data/testbed/id_ed25519.pub
#   sshd/var/sshd.log            **tests/integration/test_password_auth.py:42 硬编码这个路径**，只追加
#   sshd/var/sshd.pid            sshd 自己写
#
# 已知边界（不是缺陷，写清楚免得后人当成 bug 查）：
#   * 非 root 的 sshd 读不到 /etc/shadow，所以**密码认证在测试床上永远失败**；
#     tests/integration/test_password_auth.py 只证明密码被送达服务端（sshd.log 出现 Failed password for <user>）。
#   * 需要 root 才能验证的场景（写 /etc/ssh、改系统用户、真实 PAM 认证）不在覆盖范围内。
#   * 脚本不使用 sudo；一旦发现需要提权就停下来报错，而不是偷偷要密码。
set -euo pipefail

BASE="$HOME/.awfm-testbed"
PORT=2222
ACTION="${1:-up}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CLIENT_KEY_PRIV="$PROJECT_ROOT/data/testbed/id_ed25519"
CLIENT_KEY_SRC="$PROJECT_ROOT/data/testbed/id_ed25519.pub"

SSHD_BIN="$BASE/root/usr/sbin/sshd"
SSHD_CONFIG="$BASE/sshd/etc/sshd_config"
SSHD_LOG="$BASE/sshd/var/sshd.log"
SSHD_PID="$BASE/sshd/var/sshd.pid"
AUTHORIZED="$BASE/sshd/home/authorized_keys"

log() { printf '%s\n' "$*"; }
fail() { printf '[失败] %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

port_listening() {
  if have ss; then
    ss -ltn 2>/dev/null | grep -q "127.0.0.1:$PORT"
  else
    (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null
  fi
}

sshd_pid() {
  [ -f "$SSHD_PID" ] || return 1
  local pid
  pid="$(cat "$SSHD_PID" 2>/dev/null || true)"
  [ -n "$pid" ] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  printf '%s' "$pid"
}

ensure_dirs() {
  mkdir -p "$BASE/deb" "$BASE/keys" "$BASE/root" "$BASE/sshd/etc" "$BASE/sshd/home" "$BASE/sshd/var"
}

ensure_sshd_binary() {
  if [ -x "$SSHD_BIN" ]; then
    log "  · sshd 已就绪：$SSHD_BIN"
    return 0
  fi
  have dpkg || fail "找不到 dpkg：这个脚本只支持 Debian/Ubuntu 系的 WSL 发行版。"
  have apt-get || fail "找不到 apt-get。"
  log "  · 下载 openssh-server 的 .deb（只下载，不安装，不需要 sudo）"
  ( cd "$BASE/deb" && apt-get download openssh-server >/dev/null 2>&1 ) \
    || fail "apt-get download openssh-server 失败：检查网络/apt 源，或先跑一次 apt-get update。"
  local deb
  deb="$(ls -1t "$BASE"/deb/openssh-server*.deb 2>/dev/null | head -n1 || true)"
  [ -n "$deb" ] || fail "$BASE/deb 下没有 openssh-server*.deb。"
  log "  · 解包 $(basename "$deb") -> $BASE/root"
  dpkg -x "$deb" "$BASE/root" || fail "dpkg -x 失败。"
  [ -x "$SSHD_BIN" ] || fail "解包后仍然找不到 $SSHD_BIN。"
}

ensure_client_keys() {
  if [ -f "$BASE/keys/id_ed25519" ]; then
    return 0
  fi
  have ssh-keygen || fail "找不到 ssh-keygen。"
  log "  · 生成测试床客户端密钥 $BASE/keys/id_ed25519"
  ssh-keygen -t ed25519 -N "" -C "awfm-testbed-client" -f "$BASE/keys/id_ed25519" >/dev/null
  chmod 600 "$BASE/keys/id_ed25519"
  chmod 644 "$BASE/keys/id_ed25519.pub"
}

ensure_host_key() {
  if [ -f "$BASE/sshd/etc/ssh_host_ed25519_key" ]; then
    return 0
  fi
  have ssh-keygen || fail "找不到 ssh-keygen。"
  log "  · 生成主机密钥 $BASE/sshd/etc/ssh_host_ed25519_key"
  ssh-keygen -t ed25519 -N "" -C "awfm-testbed-host" -f "$BASE/sshd/etc/ssh_host_ed25519_key" >/dev/null
  chmod 600 "$BASE/sshd/etc/ssh_host_ed25519_key"
  chmod 644 "$BASE/sshd/etc/ssh_host_ed25519_key.pub"
}

write_sshd_config() {
  if [ -f "$SSHD_CONFIG" ] && grep -qx "Port $PORT" "$SSHD_CONFIG" 2>/dev/null; then
    log "  · sshd_config 已存在且端口正确，保持不动作：$SSHD_CONFIG"
    return 0
  fi
  log "  · 写 sshd_config：$SSHD_CONFIG"
  cat > "$SSHD_CONFIG" <<EOF
Port $PORT
ListenAddress 127.0.0.1
HostKey $BASE/sshd/etc/ssh_host_ed25519_key
PidFile $SSHD_PID
AuthorizedKeysFile $AUTHORIZED
StrictModes no
UsePAM no
PasswordAuthentication yes
PubkeyAuthentication yes
PermitRootLogin no
Subsystem sftp $BASE/root/usr/lib/openssh/sftp-server
LogLevel DEBUG1
EOF
  chmod 644 "$SSHD_CONFIG"
}

KEY_ADDED=0
add_line() {
  local line="$1"
  [ -n "$line" ] || return 0
  if grep -qxF "$line" "$AUTHORIZED" 2>/dev/null; then
    return 0
  fi
  printf '%s\n' "$line" >> "$AUTHORIZED"
  KEY_ADDED=$((KEY_ADDED + 1))
}

add_key() {
  local src="$1"
  [ -f "$src" ] || return 0
  add_line "$(head -n1 "$src")"
}

sync_authorized_keys() {
  touch "$AUTHORIZED"
  add_key "$BASE/keys/id_ed25519.pub"
  if [ -f "$CLIENT_KEY_SRC" ]; then
    add_key "$CLIENT_KEY_SRC"
  elif [ -f "$CLIENT_KEY_PRIV" ] && have ssh-keygen; then
    # 仓库里只有私钥、没有公钥时，用 ssh-keygen -y 现推公钥（只加进测试床的授权列表，不在仓库里写新文件）
    add_line "$(ssh-keygen -y -f "$CLIENT_KEY_PRIV" 2>/dev/null || true)"
    log "  · 仓库里只有 data/testbed/id_ed25519，已用 ssh-keygen -y 推出公钥加入授权列表"
  else
    log "  ! 仓库里没有 $CLIENT_KEY_PRIV：集成测试按“无测试床”跳过（见 tests/integration/support.py）。"
  fi
  chmod 700 "$BASE/sshd/home"
  chmod 600 "$AUTHORIZED"
  log "  · authorized_keys 现有 $(wc -l < "$AUTHORIZED" | tr -d ' ') 条，本次新增 $KEY_ADDED 条"
}

start_sshd() {
  if port_listening; then
    log "  · 127.0.0.1:$PORT 已在监听，不重复启动"
    return 0
  fi
  local pid
  if pid="$(sshd_pid)"; then
    log "  · 发现残留 sshd（PID $pid）但端口没起来，先停掉"
    kill "$pid" 2>/dev/null || true
    sleep 1
  fi
  log "  · 启动 sshd：$SSHD_BIN -f $SSHD_CONFIG -D -e（日志追加到 sshd.log）"
  nohup "$SSHD_BIN" -f "$SSHD_CONFIG" -D -e >> "$SSHD_LOG" 2>&1 &
  local waited=0
  while [ "$waited" -lt 30 ]; do
    if port_listening; then
      return 0
    fi
    sleep 0.5
    waited=$((waited + 1))
  done
  log "[失败] sshd 没能在 127.0.0.1:$PORT 上监听，日志末尾 20 行："
  tail -n 20 "$SSHD_LOG" >&2 || true
  exit 1
}

stop_sshd() {
  local pid
  if pid="$(sshd_pid)"; then
    log "  · 停止 sshd（PID $pid）"
    kill "$pid" 2>/dev/null || true
    local waited=0
    while [ "$waited" -lt 10 ] && kill -0 "$pid" 2>/dev/null; do
      sleep 0.5
      waited=$((waited + 1))
    done
    if kill -0 "$pid" 2>/dev/null; then
      log "  ! PID $pid 没退出，改用 kill -9"
      kill -9 "$pid" 2>/dev/null || true
    fi
    return 0
  fi
  if port_listening && have ss; then
    local found
    found="$(ss -ltnp 2>/dev/null | grep "127.0.0.1:$PORT" | grep -o 'pid=[0-9]*' | head -n1 | cut -d= -f2 || true)"
    if [ -n "$found" ]; then
      log "  · pidfile 没了但端口还在监听，按端口找到 PID $found 并停止"
      kill "$found" 2>/dev/null || true
      return 0
    fi
  fi
  log "  · 没有在跑的测试床 sshd"
}

show_status() {
  log "测试床状态（$BASE）"
  log "  发行版：$( (. /etc/os-release 2>/dev/null && printf '%s' "$PRETTY_NAME") || printf '未知')"
  log "  sshd：$SSHD_BIN"
  log "  配置：$SSHD_CONFIG"
  if port_listening; then
    log "  监听：127.0.0.1:$PORT 已就绪（PID $(sshd_pid || printf '未知')）"
  else
    log "  监听：127.0.0.1:$PORT **未就绪**"
  fi
  if [ -f "$BASE/sshd/etc/ssh_host_ed25519_key.pub" ] && have ssh-keygen; then
    log "  主机指纹：$(ssh-keygen -lf "$BASE/sshd/etc/ssh_host_ed25519_key.pub" 2>/dev/null | awk '{print $2}')"
  fi
  if [ -f "$AUTHORIZED" ]; then
    log "  授权公钥：$(wc -l < "$AUTHORIZED" | tr -d ' ') 条"
  fi
  if [ -f "$SSHD_LOG" ]; then
    log "  服务端日志：$SSHD_LOG（$(wc -c < "$SSHD_LOG" | tr -d ' ') 字节，测试会读它断言密码被送达）"
  fi
  if [ -f "$PROJECT_ROOT/data/testbed/id_ed25519" ]; then
    log "  客户端私钥：$PROJECT_ROOT/data/testbed/id_ed25519（集成测试用）"
  else
    log "  客户端私钥：**缺失** —— tests/integration 会跳过（生成方式见 docs/DECISIONS.md 的 D-012）"
  fi
}

usage() {
  log "用法：bash scripts/testbed_wsl.sh [up|status|stop]"
}

log "AWFM WSL 测试床"
case "$ACTION" in
  up)
    ensure_dirs
    ensure_sshd_binary
    ensure_client_keys
    ensure_host_key
    write_sshd_config
    sync_authorized_keys
    start_sshd
    log ""
    show_status
    log ""
    log "下一步：python -m unittest discover -s tests/integration -t .   （在 Windows 侧项目根目录执行）"
    log "停止测试床：wsl -d Ubuntu bash scripts/testbed_wsl.sh stop"
    ;;
  stop)
    stop_sshd
    log ""
    show_status
    ;;
  status)
    show_status
    ;;
  *)
    usage
    exit 2
    ;;
esac
