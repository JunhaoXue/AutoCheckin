#!/data/data/com.termux/files/usr/bin/bash
# AutoCheckin Agent - Termux Setup Script
# Run this script in Termux on your Redmi Turbo 4

set -e

echo "=== AutoCheckin Agent Setup ==="
echo ""

# Update Termux packages
echo "[1/6] Updating packages..."
pkg update -y
pkg upgrade -y

# Install required packages
echo "[2/6] Installing system packages..."
pkg install -y python android-tools openssh

# Install pip dependencies
echo "[3/6] Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Setup storage access (for screenshots)
echo "[4/6] Setting up storage access..."
termux-setup-storage || true

# Create log directory
mkdir -p logs

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo ""
echo "1. Enable Developer Options on your phone:"
echo "   Settings -> About Phone -> tap MIUI version 7 times"
echo ""
echo "2. Enable Wireless Debugging:"
echo "   Settings -> Additional Settings -> Developer Options -> Wireless Debugging"
echo ""
echo "3. Pair ADB in Termux:"
echo "   adb pair localhost:PORT  (use the pairing port shown in Wireless Debugging)"
echo "   Enter the pairing code when prompted"
echo ""
echo "4. Connect ADB:"
echo "   adb connect localhost:PORT  (use the connection port, not pairing port)"
echo ""
echo "5. Update config.yaml:"
echo "   - Set server_ws_url to your cloud server address"
echo "   - Set adb_port to your wireless debugging port"
echo "   - Set wifi_ssid to your company WiFi name"
echo ""
echo "6. Initialize uiautomator2:"
echo "   python -m uiautomator2 init"
echo ""
echo "7. Start the agent:"
echo "   python main.py"
echo ""
echo "For auto-start on boot:"
echo "   1. Install Termux:Boot from F-Droid"
echo "   2. mkdir -p ~/.termux/boot"
echo "   3. Create ~/.termux/boot/start-agent.sh with content:"
echo "      #!/data/data/com.termux/files/usr/bin/bash"
echo "      cd $(pwd)"
echo "      python main.py >> logs/agent.log 2>&1 &"
echo ""
