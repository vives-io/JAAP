# 🔄 Handoff & Runbook Guide

## Quick Start Guide

### Prerequisites Check
```bash
# 1. Verify Python version
python3 --version  # Should be 3.11+

# 2. Check runner status
cd ~/actions-runner && ./run.sh --check

# 3. Test Jamf connectivity
curl -u $JAMF_USERNAME:$JAMF_PASSWORD \
  https://your.jamfcloud.com/api/v1/auth/token

# 4. Verify GitHub secrets
gh secret list --repo YOUR_ORG/patch-automation
```

## Initial Setup

### Step 1: Clone Repository
```bash
cd /Users/melvin/Developer/GitHub/AAP
git clone https://github.com/YOUR_ORG/patch-automation.git
cd patch-automation
```

### Step 2: Install Dependencies
```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install packages
pip install -r requirements.txt
```

### Step 3: Configure Environment
```bash
# Copy environment template
cp .env.template .env

# Edit with your credentials
nano .env
```

Required environment variables:
```bash
JAMF_URL=https://your-instance.jamfcloud.com
JAMF_USERNAME=api_user
JAMF_PASSWORD=secure_password
TITLE_EDITOR_API_KEY=optional_key
GITHUB_TOKEN=ghp_xxxxxxxxxxxx
RUNNER_WORKSPACE=/Users/melvin/Developer/GitHub/AAP/patch-automation
LOG_LEVEL=INFO
CACHE_DIR=/Users/melvin/Developer/GitHub/AAP/patch-automation/cache
```

### Step 4: Setup GitHub Runner
```bash
# Download and configure runner
mkdir actions-runner && cd actions-runner
curl -o actions-runner-osx-arm64-2.311.0.tar.gz -L \
  https://github.com/actions/runner/releases/download/v2.311.0/actions-runner-osx-arm64-2.311.0.tar.gz
tar xzf ./actions-runner-osx-arm64-2.311.0.tar.gz

# Configure (interactive)
./config.sh --url https://github.com/YOUR_ORG/patch-automation \
  --token RUNNER_TOKEN_FROM_GITHUB

# Install as service
./svc.sh install
./svc.sh start
```

## Daily Operations

### Manual Application Update
```bash
# Update single application
python3 scripts/main_workflow.py \
  --app "1password" \
  --cycle "thursday_1" \
  --verbose

# Update all configured apps
python3 scripts/main_workflow.py \
  --app "all" \
  --cycle "thursday_2"
```

### Check System Status
```bash
# View recent logs
tail -f logs/patch_management.log

# Check runner status
cd ~/actions-runner && ./svc.sh status

# View cache status
python3 scripts/cache_manager.py --status

# List pending updates
python3 scripts/check_updates.py --list
```

### Trigger GitHub Action
```bash
# Via GitHub CLI
gh workflow run patch-update.yml \
  -f app_name="1Password"

# Via web interface
# Navigate to Actions tab → patch-update → Run workflow
```

## Common Tasks

### Add New Application

1. **Update configuration**:
```json
# config/applications.json
{
  "newapp": {
    "name": "New Application",
    "bundle_id": "com.company.app",
    "download_url": "https://download.url",
    "team_id": "ABCD1234",
    "patch_title": "New App"
  }
}
```

2. **Create download handler**:
```python
# scripts/downloaders/newapp.py
class NewAppDownloader(BaseDownloader):
    def get_latest_version(self):
        # Implementation
        pass
```

3. **Test locally**:
```bash
python3 scripts/test_app.py --app "newapp"
```

### Modify Patch Cycles

1. **Edit cycle configuration**:
```json
# config/patch_cycles.json
{
  "cycles": [
    {
      "name": "Thursday 1",
      "smart_group": "Patch_Cycle_Thu1",
      "week": 1,
      "time": "09:00"
    }
  ]
}
```

2. **Update smart groups in Jamf**:
   - Navigate to Jamf Pro → Smart Computer Groups
   - Create/modify groups with appropriate criteria

### Handle Failed Updates

1. **Check error logs**:
```bash
grep ERROR logs/patch_management.log | tail -20
```

2. **Retry single application**:
```bash
python3 scripts/main_workflow.py \
  --app "failed_app" \
  --retry \
  --verbose
```

3. **Clear cache if needed**:
```bash
rm -rf cache/failed_app/*
```

4. **Manual intervention**:
   - Download package manually
   - Process with: `python3 scripts/process_manual.py --package /path/to/package.pkg`

## Troubleshooting Procedures

### Runner Not Starting
```bash
# Check service logs
cd ~/actions-runner
cat _diag/Runner_*.log

# Restart service
./svc.sh stop
./svc.sh start

# Re-register if needed
./config.sh remove --token REMOVAL_TOKEN
./config.sh --url REPO_URL --token NEW_TOKEN
```

### Jamf Authentication Failures
```bash
# Test authentication
python3 -c "
from scripts.patch_management import JamfPatchManager
import os
from dotenv import load_dotenv
load_dotenv()
manager = JamfPatchManager(
    os.getenv('JAMF_URL'),
    os.getenv('JAMF_USERNAME'),
    os.getenv('JAMF_PASSWORD')
)
print('Authentication successful')
"
```

### Package Download Issues
```bash
# Test download directly
curl -L -o test.pkg "DOWNLOAD_URL"

# Check with verbose logging
python3 scripts/download_package.py \
  --app "problematic_app" \
  --debug
```

## Maintenance Procedures

### Weekly Tasks
- [ ] Review error logs
- [ ] Check disk space
- [ ] Verify runner health
- [ ] Update application versions

### Monthly Tasks
- [ ] Clean old cache files
- [ ] Update dependencies
- [ ] Review Jamf policies
- [ ] Test disaster recovery

### Quarterly Tasks
- [ ] Security audit
- [ ] Performance review
- [ ] Documentation update
- [ ] Team training

## Emergency Procedures

### Rollback Failed Deployment
```bash
# 1. Disable patch policy
python3 scripts/emergency_disable.py --policy "PolicyName"

# 2. Revert to previous version
python3 scripts/rollback.py --app "AppName" --version "Previous"

# 3. Notify team
./scripts/send_alert.sh "Rollback initiated for AppName"
```

### System Recovery
```bash
# Full system restore
./scripts/disaster_recovery.sh --restore-point "2024-01-15"
```

## Secrets & Credentials

### Location of Secrets
- **GitHub Secrets**: Repository Settings → Secrets and variables → Actions
- **Local .env file**: `/Users/melvin/Developer/GitHub/AAP/patch-automation/.env`
- **Keychain items**: `security find-generic-password -s "JamfAPI"`

### Rotating Credentials
```bash
# 1. Generate new Jamf API credentials in Jamf Pro

# 2. Update GitHub secrets
gh secret set JAMF_USERNAME
gh secret set JAMF_PASSWORD

# 3. Update local environment
nano .env

# 4. Test new credentials
python3 scripts/test_auth.py
```

## Monitoring & Alerts

### Log Locations
- **Application logs**: `logs/patch_management.log`
- **Runner logs**: `~/actions-runner/_diag/`
- **GitHub Actions logs**: Web UI → Actions tab
- **System logs**: `/var/log/system.log`

### Alert Configuration
```bash
# Email alerts
ALERT_EMAIL="admin@company.com"

# Slack webhook
SLACK_WEBHOOK="https://hooks.slack.com/services/XXX/YYY/ZZZ"
```

## Support Contacts

| Role | Name | Contact | Hours |
|------|------|---------|-------|
| Primary Admin | Your Name | email@company.com | 9-5 PST |
| Jamf Admin | Admin Name | jamf@company.com | 9-5 PST |
| Security Team | Security | security@company.com | 24/7 |
| Vendor Support | Various | See vendor docs | Varies |

## Quick Reference Commands

```bash
# Start workflow
make run-workflow APP=1password

# Check status
make status

# View logs
make logs

# Run tests
make test

# Deploy to production
make deploy

# Emergency stop
make emergency-stop
```