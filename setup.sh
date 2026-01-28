#!/bin/bash

clear
echo "=============================================="
echo " Shadow X Bot v11 Installer"
echo " © 2026 Shadow Bot"
echo " ALL RIGHTS RESERVED"
echo " Do NOT change credits"
echo "=============================================="
echo ""

# ===== CONFIG =====
RAW_BASE_URL="https://github.com/kakashiplayz26606/Shadowxv11"
MAIN_FILE="shadowv11.py"
REQ_FILE="requirements.txt"

# ===== CHECK PYTHON =====
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python3 not found"
    exit 1
fi

# ===== DOWNLOAD FILES =====
echo "[+] Downloading files..."
curl -fsSL "$RAW_BASE_URL/$MAIN_FILE" -o $MAIN_FILE || { echo "Failed to download shadowv11.py"; exit 1; }
curl -fsSL "$RAW_BASE_URL/$REQ_FILE" -o $REQ_FILE || { echo "Failed to download rqr.txt"; exit 1; }

# ===== INSTALL REQUIREMENTS =====
echo "[+] Installing requirements..."
python3 -m pip install --upgrade pip
pip install -r $REQ_FILE

# ===== USER INPUT =====
echo ""
echo "===== BOT CONFIGURATION ====="
read -p "Enter Bot Token: " BOT_TOKEN
read -p "Enter Owner ID: " OWNER_ID
read -p "Enter Prefix (default !): " PREFIX
read -p "Enter Payment UPI: " PAYMENT_UPI

PREFIX=${PREFIX:-!}

# ===== REPLACE CONFIG IN PY FILE =====
echo "[+] Applying configuration..."

sed -i "s|^TOKEN *=.*|TOKEN = \"${BOT_TOKEN}\"|g" $MAIN_FILE
sed -i "s|^MAIN_OWNER_ID *=.*|MAIN_OWNER_ID = ${OWNER_ID}|g" $MAIN_FILE
sed -i "s|^PAYMENT_UPI *=.*|PAYMENT_UPI = \"${PAYMENT_UPI}\"|g" $MAIN_FILE
sed -i "s|^PREFIX *=.*|PREFIX = \"${PREFIX}\"|g" $MAIN_FILE

echo ""
echo "[✓] Configuration applied successfully"
echo ""

# ===== START OPTION =====
read -p "Do you want to start the bot now? (y/n): " START_NOW
if [[ "$START_NOW" == "y" || "$START_NOW" == "Y" ]]; then
    echo "[+] Starting Shadow X Bot..."
    python3 $MAIN_FILE
else
    echo "Run manually using:"
    echo "python3 shadowv11.py"
fi
