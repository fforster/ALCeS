#!/usr/bin/env bash
# ============================================================================
# open_nlhpc.sh — Fase 96: abre la webapp de NLHPC en tu navegador con UN
# comando, sin importar a que login node (leftraru1, leftraru2, ...) te
# mande el balanceador.
#
# Antes: la app se lanzaba con nohup en una conexion ssh y el tunel en otra;
# si el balanceador mandaba cada una a un nodo distinto, el tunel llegaba a
# un nodo sin app, y cada instancia con nohup quedaba huerfana en el nodo.
# Ahora app y tunel viajan en la MISMA conexion ssh: el tunel llega siempre
# al nodo donde corre la app, y al cerrar (Ctrl+C) se van las dos juntas.
#
# Uso (desde tu maquina, Git Bash en Windows / Linux / macOS):
#     ./open_nlhpc.sh [puerto_local]          # default 5000
#
# Variables opcionales:
#     ALCES_SSH_HOST     alias ssh de NLHPC            (default: nlhpc)
#     ALCES_REMOTE_REPO  clon del repo en NLHPC, relativo a tu home o absoluto
#                        (default: AUTOSIM)
#     ALCES_NO_BROWSER=1 no abrir el navegador (solo imprime la URL)
# ============================================================================
set -euo pipefail
# Git Bash (MSYS) reescribe argumentos que parecen rutas POSIX: sin esto,
# "-L 5000:/home/<user>/..." llegaria a ssh como "5000:C:/Program Files/Git/home/...".
export MSYS_NO_PATHCONV=1

LPORT="${1:-5000}"
HOST="${ALCES_SSH_HOST:-nlhpc}"
REPO="${ALCES_REMOTE_REPO:-AUTOSIM}"
URL="http://127.0.0.1:$LPORT/"

# El reenvio -L <puerto>:<socket> necesita la ruta ABSOLUTA del socket remoto.
REMOTE_HOME="$(ssh -n -o BatchMode=yes "$HOST" 'printf %s "$HOME"' 2>/dev/null)"
[ -n "$REMOTE_HOME" ] || { echo "no se pudo conectar a '$HOST' (ssh)" >&2; exit 1; }
case "$REPO" in /*) REMOTE_LCL="$REPO/exploration/lightcurvelynx" ;;
                *)  REMOTE_LCL="$REMOTE_HOME/$REPO/exploration/lightcurvelynx" ;; esac
# Un socket por sesion: varias sesiones (o varias personas) no se pisan.
SOCK="$REMOTE_HOME/.alces/webapp-$(date +%s)-$RANDOM.sock"

open_browser() {
  if [ "${ALCES_NO_BROWSER:-}" = 1 ]; then return; fi
  if command -v cmd.exe >/dev/null 2>&1; then cmd.exe /c start "" "$1" >/dev/null 2>&1
  elif command -v open >/dev/null 2>&1; then open "$1"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$1" >/dev/null 2>&1
  else echo "» abre $1 en tu navegador"; fi
}

# Abrir el navegador recien cuando la app responde (arranca en unos segundos).
(
  for _ in $(seq 1 60); do
    sleep 2
    # ">/dev/null" lo resuelve bash; "-o /dev/null" no sirve en Git Bash con
    # MSYS_NO_PATHCONV=1 (curl.exe nativo intentaria escribir en C:\dev\null).
    if curl -s --max-time 5 "$URL" >/dev/null; then open_browser "$URL"; echo "» $URL"; exit 0; fi
  done
  echo "» la app no respondio en 2 minutos -- revisar la salida de arriba" >&2
) &
WAITER=$!
trap 'kill $WAITER 2>/dev/null || true' EXIT

# -tt: terminal remota, asi Ctrl+C / cerrar la ventana llega a la app (SIGINT/SIGHUP)
# LogLevel=ERROR: oculta los "channel N: open failed" del sondeo mientras la app arranca
ssh -tt -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o LogLevel=ERROR \
    -L "127.0.0.1:$LPORT:$SOCK" "$HOST" \
    "bash '$REMOTE_LCL/webapp/serve_nlhpc.sh' '$SOCK'"
