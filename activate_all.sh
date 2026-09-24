#!/bin/bash
# ============================================================================
# activate_all.sh — activa TODO lo necesario para trabajar con el pipeline.
# ----------------------------------------------------------------------------
# Uso (siempre con 'source', nunca ejecutandolo directo):
#     cd ~/AUTOSIM
#     source activate_all.sh
#
# Detecta automaticamente donde esta el venv (evita el problema de asumir
# una ruta fija) y carga SNANA + variables de entorno.
# ============================================================================

# --- 0. modulo base de Python (el venv depende de sus libs en runtime,
#         p.ej. libiomp5.so — sin esto el interprete del venv no arranca) ---
module load python/3.12.3-legacy-skylake
echo "✓ modulo python/3.12.3-legacy-skylake cargado (runtime libs del venv)"

# --- 1. localizar y activar el venv (busca en un par de ubicaciones tipicas) ---
VENV_CANDIDATES=(
    "./venv"
    "./pipeline/venv"
)
VENV_FOUND=""
for v in "${VENV_CANDIDATES[@]}"; do
    if [ -f "$v/bin/activate" ]; then
        VENV_FOUND="$v"
        break
    fi
done

if [ -z "$VENV_FOUND" ]; then
    echo "⚠ No se encontro ningun venv en: ${VENV_CANDIDATES[*]}"
    echo "  Buscando en todo AUTOSIM (puede tardar unos segundos)..."
    FOUND_ACTIVATE=$(find . -maxdepth 4 -iname "activate" -path "*/bin/*" 2>/dev/null | head -1)
    if [ -n "$FOUND_ACTIVATE" ]; then
        VENV_FOUND=$(dirname "$(dirname "$FOUND_ACTIVATE")")
        echo "  ✓ encontrado: $VENV_FOUND"
    else
        echo "  ✗ no se encontro ningun venv. Crea uno con:"
        echo "      python3 -m venv pipeline/venv"
        return 1 2>/dev/null || exit 1
    fi
fi

source "$VENV_FOUND/bin/activate"
echo "✓ venv activado: $VENV_FOUND"

# --- 2. modulo SNANA (Lmod es case-sensitive: SNANA, no snana) ---
module load SNANA/11.05p
echo "✓ modulo SNANA/11.05p cargado"

# --- 3. variables de entorno ---
# SNDATA_ROOT: de cada usuario (arbol publico de SNANA + salida SIM/).
export SNDATA_ROOT="${SNDATA_ROOT:-$HOME/SNDATA_ROOT}"
echo "✓ SNDATA_ROOT=$SNDATA_ROOT"
[ -d "$SNDATA_ROOT" ] || echo "  ⚠ no existe — ver INSTALL.md seccion 4"

# ALCES_DATA (Fase 94): copia compartida de solo lectura con run_SNANA/ y
# OTMODEL_NON1ASED/. Definirla en ~/.bashrc; sin ella cae a $HOME.
export ALCES_DATA="${ALCES_DATA:-${SNANA_HOME:-$HOME}}"
echo "✓ ALCES_DATA=$ALCES_DATA"
[ -d "$ALCES_DATA/run_SNANA" ] || echo "  ⚠ no contiene run_SNANA/ — exportar ALCES_DATA (ver INSTALL.md)"

# --- 4. verificacion rapida ---
echo ""
echo "Verificacion:"
echo "  snlc_sim.exe: $(which snlc_sim.exe 2>/dev/null || echo 'NO ENCONTRADO')"
echo "  python:       $(which python)"
