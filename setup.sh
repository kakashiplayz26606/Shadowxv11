#!/bin/bash

set -e

clear
echo "=============================================="
echo " Shadow X Bot v11 Installer"
echo " © 2026 Shadow Bot"
echo " ALL RIGHTS RESERVED"
echo " Do NOT change credits"
echo "=============================================="
echo ""

RAW_BASE_URL="https://raw.githubusercontent.com/kakashiplayz26606/Shadowxv11/main"
MAIN_FILE="shadowv11.py"
REQ_FILE="requirements.txt"
VENV_DIR=".shadowx_venv"

# ===== CHECK PYTHON =====
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python3 not installed"
    exit 1
fi

# ===== DOWNLOAD FILES =====
echo "[+] Downloading files..."
curl -fsSL "$RAW_BASE_URL/$MAIN_FILE" -o "$MAIN_FILE"
curl -fsSL "$RAW_BASE_URL/$REQ_FILE" -o "$REQ_FILE"

# ===== CREATE VENV =====
if [ ! -d "$VENV_DIR" ]; then
    echo "[+] Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

# ===== INSTALL DEPENDENCIES =====
echo "[+] Installing dependencies inside venv..."
pip install --upgrade pip
pip install -r "$REQ_FILE"

# ===== USER INPUT =====
echo ""
echo "===== BOT CONFIGURATION ====="
read -p "Enter Bot Token: " BOT_TOKEN
read -p "Enter Main Owner ID: " OWNER_ID
read -p "Enter Prefix (default !): " PREFIX
read -p "Enter Payment UPI: " PAYMENT_UPI
read -p "Enter Footer / Version text: " VERSION_TEXT

PREFIX=${PREFIX:-!}
VERSION_TEXT=${VERSION_TEXT:-Shadow X v11}

# ===== SAFE CONFIG REPLACE =====
echo "[+] Applying configuration..."

sed -i "s|^TOKEN *=.*|TOKEN = \"${BOT_TOKEN}\"|" "$MAIN_FILE"
sed -i "s|^MAIN_OWNER_ID *=.*|MAIN_OWNER_ID = ${OWNER_ID}|" "$MAIN_FILE"
sed -i "s|^PAYMENT_UPI *=.*|PAYMENT_UPI = \"${PAYMENT_UPI}\"|" "$MAIN_FILE"
sed -i "s|^PREFIX *=.*|PREFIX = \"${PREFIX}\"|" "$MAIN_FILE"
sed -i "s|^VERSION *=.*|VERSION = \"${VERSION_TEXT}\"|" "$MAIN_FILE"

echo ""
echo "[✓] Configuration updated successfully"

# ===== START OPTION =====
read -p "Start bot now? (y/n): " RUN
if [[ "$RUN" == "y" || "$RUN" == "Y" ]]; then
    echo "[+] Starting Shadow X Bot..."
    python "$MAIN_FILE"
else
    echo "To start later:"
    echo "source $VENV_DIR/bin/activate && python shadowv11.py"
fi
