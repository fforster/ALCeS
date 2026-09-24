#!/usr/bin/env bash
# ============================================================================
# serve_nlhpc.sh — Fase 96: corre la webapp en el login node donde caiga la
# conexion ssh, servida en un socket Unix privado. NO se llama a mano: lo
# ejecuta webapp/open_nlhpc.sh (desde tu maquina) en la MISMA conexion ssh
# que abre el tunel, asi el tunel siempre llega al nodo donde corre la app
# (leftraru1, leftraru2, ... da igual).
#
# La app muere con la conexion: un vigilante revisa cada 3 s que el proceso
# padre (la sesion de sshd) siga vivo. No se depende de SIGHUP, que solo
# llega si ssh consiguio una terminal remota (-tt) -- en la prueba real, un
# lanzamiento sin terminal local dejo la app huerfana en el nodo.
#
# Uso (remoto):  bash serve_nlhpc.sh /home/<user>/.alces/webapp-<id>.sock
# ============================================================================
set -uo pipefail

SOCK="${1:?uso: serve_nlhpc.sh <socket>}"
LCL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOCK_DIR="$(dirname "$SOCK")"
PARENT=$PPID

mkdir -p "$SOCK_DIR"
chmod 700 "$SOCK_DIR"
# sockets de sesiones que murieron sin limpiar (p.ej. el nodo se reinicio): 7+ dias
find "$SOCK_DIR" -maxdepth 1 -name 'webapp-*.sock' -mtime +7 -delete 2>/dev/null || true

module load python/3.12.3-legacy-skylake >/dev/null 2>&1
# shellcheck disable=SC1091
source "$LCL_DIR/venv/bin/activate" || exit 1

APP=""
stop() {
  if [ -n "$APP" ] && kill -0 "$APP" 2>/dev/null; then
    pkill -TERM -P "$APP" 2>/dev/null   # kernels de Explore que esten corriendo
    kill -TERM "$APP" 2>/dev/null
    for _ in 1 2 3 4 5; do kill -0 "$APP" 2>/dev/null || break; sleep 1; done
    kill -KILL "$APP" 2>/dev/null
  fi
  rm -f "$SOCK"
}
trap stop EXIT
trap 'exit 0' HUP INT TERM

echo "» LightCurveLynx webapp on $(hostname) (socket $SOCK)"
echo "» close this window or press Ctrl+C to stop it"
cd "$LCL_DIR"
python3 webapp/app.py --socket "$SOCK" &
APP=$!

# Vigilante: termina cuando la app muere sola o cuando se cae la conexion.
while kill -0 "$APP" 2>/dev/null; do
  if ! kill -0 "$PARENT" 2>/dev/null || [ "$(ps -o ppid= -p $$ | tr -d ' ')" != "$PARENT" ]; then
    echo "» ssh connection closed -- stopping the webapp"
    exit 0
  fi
  sleep 3
done
wait "$APP"
