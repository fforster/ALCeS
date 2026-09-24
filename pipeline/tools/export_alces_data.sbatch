#!/bin/bash
#SBATCH -J export_alces_data
#SBATCH -p general
#SBATCH -n 1
#SBATCH --mem=2G
#SBATCH -t 04:00:00
#SBATCH -o export_alces_data_%j.out
# ============================================================================
# export_alces_data.sbatch — Fase 94: arma la carpeta compartida ALCES_DATA.
# ----------------------------------------------------------------------------
# Copia desde la cuenta que tiene los datos curados (hoy: mvalenzuela) todo
# lo que el pipeline lee y que NO esta en git:
#
#     $DEST/run_SNANA/            plantillas, SEARCHEFF, SIMGEN_INCLUDE (~18 GB)
#     $DEST/OTMODEL_NON1ASED/     modelos VC25 (~1 GB)
#     $DEST/bin/snana_custom/     snlc_sim.exe con MXOBS_SIMLIB ampliado (DDF)
#     $DEST/SNDATA_ROOT_*.tar.gz  arbol publico de SNANA (~1.6 GB)
#
# y reescribe, SOLO en la copia, las rutas absolutas de los SIMGEN_INCLUDE:
#
#     $HOME/run_SNANA          -> ${ALCES_DATA}/run_SNANA
#     $HOME/OTMODEL_NON1ASED   -> ${ALCES_DATA}/OTMODEL_NON1ASED
#     $HOME/SNDATA_ROOT        -> $SNDATA_ROOT   (arbol publico, de cada usuario)
#
# ${ALCES_DATA} lo expande el compilador de campanhas al generar los .INPUT;
# $SNDATA_ROOT lo expande SNANA. Los originales en $HOME no se tocan.
#
# Uso (en NLHPC, desde la raiz del repo, como el duenho de los datos):
#     sbatch pipeline/tools/export_alces_data.sbatch /ruta/compartida/alces_data
#
# Es idempotente (rsync): re-correrlo actualiza la copia con lo nuevo.
# Despues, cada miembro del equipo agrega a su ~/.bashrc:
#     export ALCES_DATA=/ruta/compartida/alces_data
# ============================================================================
set -euo pipefail

DEST="${1:?uso: sbatch export_alces_data.sbatch <DEST>}"
SRC_HOME="${SRC_HOME:-$HOME}"
REPO="${SLURM_SUBMIT_DIR:-$(pwd)}"

[ -d "$SRC_HOME/run_SNANA" ] || { echo "no existe $SRC_HOME/run_SNANA" >&2; exit 1; }
[ -f "$REPO/pipeline/paths.py" ] || { echo "correr sbatch desde la raiz del repo" >&2; exit 1; }
# La reescritura de rutas es solo para la copia: nunca sobre los originales.
if [ "$(realpath -m "$DEST")" = "$(realpath -m "$SRC_HOME")" ]; then
  echo "DEST no puede ser $SRC_HOME (se reescribirian los originales)" >&2; exit 1
fi
mkdir -p "$DEST/bin"

echo "» copiando a $DEST ..."
rsync -a --delete --exclude '.git' "$SRC_HOME/run_SNANA/" "$DEST/run_SNANA/"
rsync -a --delete "$SRC_HOME/OTMODEL_NON1ASED/" "$DEST/OTMODEL_NON1ASED/"
# Arbol publico de SNANA: cada usuario lo descomprime en su $SNDATA_ROOT
# (el modulo SNANA de NLHPC no define uno). Trae MWDUST, filtros y el
# modelo NON1ASED.V19_CC+HostXT que usan 6 clases.
for tgz in "$SRC_HOME"/SNDATA_ROOT/SNDATA_ROOT_*.tar.gz; do
  [ -f "$tgz" ] && rsync -a "$tgz" "$DEST/"
done
if [ -x "$REPO/bin/snana_custom/snlc_sim.exe" ]; then
  rsync -a --delete "$REPO/bin/snana_custom/" "$DEST/bin/snana_custom/"
else
  echo "  ⚠ no hay $REPO/bin/snana_custom/snlc_sim.exe — las clases DDF necesitan ese binario"
fi

echo "» reescribiendo rutas absolutas en los .INPUT de la copia ..."
n=0
while IFS= read -r -d '' f; do
  sed -i -e "s#$SRC_HOME/run_SNANA#\${ALCES_DATA}/run_SNANA#g" \
         -e "s#$SRC_HOME/OTMODEL_NON1ASED#\${ALCES_DATA}/OTMODEL_NON1ASED#g" \
         -e "s#$SRC_HOME/SNDATA_ROOT#\$SNDATA_ROOT#g" "$f"
  n=$((n+1))
done < <(grep -rlIZ --include='*.INPUT' "$SRC_HOME/" "$DEST/run_SNANA" "$DEST/OTMODEL_NON1ASED" || true)
echo "  $n archivos reescritos"

# Lectura para todos; quien entra lo controla el directorio padre (grupo/ACL).
chmod -R u+rwX,go+rX,go-w "$DEST"

echo "» verificacion"
du -sh "$DEST"/*
left=$(grep -rlI --include='*.INPUT' "$SRC_HOME/" "$DEST" || true)
if [ -n "$left" ]; then
  echo "  ✗ quedan .INPUT con rutas a $SRC_HOME:"; echo "$left" | sed 's/^/    /'
  exit 1
fi
echo "  ✓ ningun .INPUT apunta a $SRC_HOME"
echo "DONE — exportar en cada cuenta:  export ALCES_DATA=$DEST"
