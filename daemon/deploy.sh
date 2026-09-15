#!/bin/bash
# deploy.sh — Run tests and restart nexus-daemon via PM2
# Usage: bash texty/deploy.sh

set -e

echo "=== nexus-daemon deploy ==="

# 1. Run tests
echo "Running tests..."
python3 -m pytest texty/tests/test_nexus_daemon.py -v --tb=short
TEST_RESULT=$?

if [ $TEST_RESULT -ne 0 ]; then
    echo "❌ Tests failed — aborting deploy"
    exit 1
fi

echo "✅ All tests passed"

# 2. Restart daemon
echo "Restarting nexus-daemon..."
pm2 restart nexus-daemon

# 3. Verify
sleep 3
pm2 info nexus-daemon 2>/dev/null | grep -E "status|uptime|restarts"
echo ""
echo "=== Deploy complete ==="