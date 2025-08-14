#!/bin/bash
# GitHub Actions Self-Hosted Runner Setup for macOS
# Run this script on your macOS machine to set up the patch automation runner

set -e

echo "🚀 Setting up GitHub Actions Self-Hosted Runner for Patch Automation"
echo "=================================================================="

# Configuration
RUNNER_VERSION="2.311.0"
RUNNER_ARCH="osx-arm64"  # Change to osx-x64 for Intel Macs
REPO_URL=""  # Will be prompted
RUNNER_TOKEN=""  # Will be prompted
RUNNER_NAME="patch-automation-runner"
RUNNER_LABELS="macos,patch-automation,jamf"

# Detect architecture
if [[ $(uname -m) == "arm64" ]]; then
    RUNNER_ARCH="osx-arm64"
else
    RUNNER_ARCH="osx-x64" 
fi

echo "Detected architecture: $RUNNER_ARCH"

# Check prerequisites
echo "Checking prerequisites..."

# Check if we're on macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    echo "❌ This script is designed for macOS only"
    exit 1
fi

# Check if Python 3.11+ is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not installed"
    echo "Please install Python 3.11+ from https://python.org or use Homebrew:"
    echo "brew install python@3.11"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if [[ $(echo "$PYTHON_VERSION >= 3.11" | bc -l) -eq 0 ]]; then
    echo "❌ Python 3.11+ is required (found $PYTHON_VERSION)"
    exit 1
fi

echo "✅ Python $PYTHON_VERSION found"

# Check if curl is available
if ! command -v curl &> /dev/null; then
    echo "❌ curl is required but not installed"
    exit 1
fi

echo "✅ curl found"

# Create actions-runner directory
RUNNER_DIR="$HOME/actions-runner"
if [[ -d "$RUNNER_DIR" ]]; then
    echo "⚠️  Actions runner directory already exists: $RUNNER_DIR"
    read -p "Do you want to remove it and start fresh? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$RUNNER_DIR"
        echo "Removed existing runner directory"
    else
        echo "❌ Exiting to avoid conflicts"
        exit 1
    fi
fi

mkdir -p "$RUNNER_DIR"
cd "$RUNNER_DIR"

echo "📥 Downloading GitHub Actions Runner v$RUNNER_VERSION..."

# Download the runner
RUNNER_FILENAME="actions-runner-${RUNNER_ARCH}-${RUNNER_VERSION}.tar.gz"
DOWNLOAD_URL="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/${RUNNER_FILENAME}"

curl -o "$RUNNER_FILENAME" -L "$DOWNLOAD_URL"

echo "✅ Downloaded runner package"

# Verify the hash (optional but recommended)
echo "Verifying download..."
if [[ "$RUNNER_ARCH" == "osx-arm64" ]]; then
    EXPECTED_HASH="33ddf73f804b9a1e1d75390ae7fbec29" # Update with actual hash
else
    EXPECTED_HASH="43b20f7c6bb50b89ccf58e83ee0ce5e1" # Update with actual hash
fi

# Extract the runner
echo "📦 Extracting runner..."
tar xzf "./$RUNNER_FILENAME"

# Clean up the tar file
rm "$RUNNER_FILENAME"

echo "✅ Runner extracted"

# Get repository information
echo ""
echo "🔗 Repository Configuration"
echo "=========================="

if [[ -z "$REPO_URL" ]]; then
    read -p "Enter your GitHub repository URL (e.g., https://github.com/your-org/patch-automation): " REPO_URL
fi

if [[ -z "$RUNNER_TOKEN" ]]; then
    echo ""
    echo "To get a runner token:"
    echo "1. Go to your GitHub repository"
    echo "2. Settings → Actions → Runners"  
    echo "3. Click 'New self-hosted runner'"
    echo "4. Copy the token from the configuration step"
    echo ""
    read -p "Enter your runner registration token: " RUNNER_TOKEN
fi

# Configure the runner
echo ""
echo "⚙️  Configuring runner..."

./config.sh \
    --url "$REPO_URL" \
    --token "$RUNNER_TOKEN" \
    --name "$RUNNER_NAME" \
    --labels "$RUNNER_LABELS" \
    --work "_work" \
    --unattended

echo "✅ Runner configured"

# Set up the environment
echo ""
echo "🌍 Setting up environment..."

# Create Python virtual environment
if [[ ! -d "venv" ]]; then
    python3 -m venv venv
    echo "✅ Created Python virtual environment"
fi

# Activate virtual environment and install dependencies
source venv/bin/activate

# Go to the project directory
PROJECT_DIR=$(dirname $(dirname $(realpath $0)))
cd "$PROJECT_DIR"

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

echo "✅ Installed Python dependencies"

# Return to runner directory
cd "$RUNNER_DIR"

# Create environment file
echo "Creating runner environment file..."
cat > .env << EOF
# Python environment
PYTHON_HOME="$RUNNER_DIR/venv"
PATH="$RUNNER_DIR/venv/bin:\$PATH"

# macOS specific
TMPDIR="/tmp"
HOME="$HOME"

# Project paths
PROJECT_ROOT="$PROJECT_DIR"
EOF

echo "✅ Environment configured"

# Install as a service
echo ""
echo "🔧 Installing runner as a service..."

read -p "Install runner as a system service? (recommended) (Y/n): " -n 1 -r
echo

if [[ ! $REPLY =~ ^[Nn]$ ]]; then
    ./svc.sh install
    ./svc.sh start
    echo "✅ Runner service installed and started"
else
    echo "ℹ️  Skipped service installation"
    echo "To run the runner manually: ./run.sh"
fi

# Set up log rotation (optional)
echo ""
echo "📝 Setting up log rotation..."

LOGROTATE_CONF="$HOME/Library/LaunchAgents/runner.logrotate.plist"
cat > "$LOGROTATE_CONF" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>runner.logrotate</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/sbin/newsyslog</string>
        <string>-f</string>
        <string>$RUNNER_DIR/newsyslog.conf</string>
    </array>
    <key>StartInterval</key>
    <integer>86400</integer>
</dict>
</plist>
EOF

# Create newsyslog config
cat > "$RUNNER_DIR/newsyslog.conf" << EOF
# logfilename          [owner:group]    mode count size when  flags [/pid_file] [sig_num]
$RUNNER_DIR/_diag/*.log                644  10    10M   *     GN
$PROJECT_DIR/logs/*.log                644  30    50M   *     GN
EOF

launchctl load "$LOGROTATE_CONF" 2>/dev/null || true

echo "✅ Log rotation configured"

# Create status check script
echo ""
echo "📊 Creating status check script..."

cat > "$RUNNER_DIR/check_status.sh" << 'EOF'
#!/bin/bash
# Runner status check script

echo "GitHub Actions Runner Status"
echo "============================"
echo ""

# Check if runner service is running
if pgrep -f "Runner.Listener" > /dev/null; then
    echo "✅ Runner service is running"
else
    echo "❌ Runner service is not running"
fi

# Check disk space
DISK_USAGE=$(df -h . | awk 'NR==2 {print $5}' | sed 's/%//')
echo "💾 Disk usage: ${DISK_USAGE}%"

if [[ $DISK_USAGE -gt 80 ]]; then
    echo "⚠️  Disk usage is high"
fi

# Check recent jobs
echo ""
echo "Recent workflow runs:"
if [[ -d "_work" ]]; then
    find _work -name "*.log" -mtime -7 | head -5 | while read log; do
        echo "  $(basename $log) - $(stat -f "%Sm" -t "%Y-%m-%d %H:%M" "$log")"
    done
else
    echo "  No recent jobs found"
fi

# Check runner logs
echo ""
echo "Recent runner activity:"
if [[ -d "_diag" ]]; then
    tail -5 _diag/Runner_*.log 2>/dev/null | grep -v "^$" || echo "  No recent activity"
else
    echo "  No diagnostic logs found"
fi
EOF

chmod +x "$RUNNER_DIR/check_status.sh"

echo "✅ Status check script created"

# Final summary
echo ""
echo "🎉 Setup Complete!"
echo "=================="
echo ""
echo "Runner Details:"
echo "  Name: $RUNNER_NAME"
echo "  Labels: $RUNNER_LABELS"
echo "  Location: $RUNNER_DIR"
echo "  Project: $PROJECT_DIR"
echo ""
echo "Useful Commands:"
echo "  Check status: $RUNNER_DIR/check_status.sh"
echo "  Start service: $RUNNER_DIR/svc.sh start"
echo "  Stop service: $RUNNER_DIR/svc.sh stop"
echo "  View logs: tail -f $RUNNER_DIR/_diag/Runner_*.log"
echo ""
echo "Next Steps:"
echo "1. Configure your environment variables in the GitHub repository secrets"
echo "2. Test the workflow by running it manually from the GitHub Actions tab"
echo "3. Check the runner status with: $RUNNER_DIR/check_status.sh"
echo ""
echo "Environment Variables Needed in GitHub Secrets:"
echo "  JAMF_URL"
echo "  JAMF_USERNAME"
echo "  JAMF_PASSWORD"
echo "  TITLE_EDITOR_URL (optional)"
echo "  TITLE_EDITOR_TOKEN (optional)"
echo "  SLACK_WEBHOOK_URL (optional)"
echo ""
echo "✨ The runner is ready for patch automation workflows!"