#!/data/data/com.termux/files/usr/bin/bash
# AutoCheckin Agent - Termux Setup Script
# Run this script in Termux on your Redmi Turbo 4

set -e

echo "=== AutoCheckin Agent Setup ==="
echo ""

# Update Termux packages (auto-answer config prompts with default)
echo "[1/7] Updating packages..."
pkg update -y -o Dpkg::Options::="--force-confold"
pkg upgrade -y -o Dpkg::Options::="--force-confold"

# Install required system packages
echo "[2/7] Installing system packages..."
pkg install -y python android-tools openssh \
    libxml2 libxslt libjpeg-turbo zlib \
    ndk-sysroot clang make pkg-config

# Install Termux's pre-built python packages to avoid compiling from source
# These are native C extensions that are hard to compile on phone
echo "[3/7] Installing pre-built native Python packages..."
pkg install -y python-lxml python-pillow || true

# Create virtual environment with access to system packages
echo "[4/7] Creating Python virtual environment..."
rm -rf venv
python -m venv --system-site-packages venv
source venv/bin/activate

# Install remaining Python dependencies (lxml and Pillow already from system)
echo "[5/7] Installing Python dependencies..."
pip install uiautomator2==3.2.2 websockets==13.0 apscheduler==3.10.4 pyyaml==6.0.1

# Setup storage access (for screenshots)
echo "[6/7] Setting up storage access..."
termux-setup-storage || true

# Create log directory
mkdir -p logs

echo "[7/7] Setup complete!"
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
echo "6. Activate venv and initialize uiautomator2:"
echo "   source venv/bin/activate"
echo "   python -m uiautomator2 init"
echo ""
echo "7. Start the agent:"
echo "   source venv/bin/activate"
echo "   python main.py"
echo ""
echo "For auto-start on boot:"
echo "   1. Install Termux:Boot from F-Droid"
echo "   2. mkdir -p ~/.termux/boot"
echo "   3. Create ~/.termux/boot/start-agent.sh with content:"
echo "      #!/data/data/com.termux/files/usr/bin/bash"
echo "      cd $(pwd)"
echo "      source venv/bin/activate"
echo "      python main.py >> logs/agent.log 2>&1 &"
echo ""
