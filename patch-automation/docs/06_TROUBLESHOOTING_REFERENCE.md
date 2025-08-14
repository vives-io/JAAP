# 🧰 Troubleshooting Reference

## Common Issues & Resolutions

### 1. Authentication Failures

#### Issue: Jamf API Authentication Failed
**Error Message**: 
```
Error: Authentication failed: 401 Unauthorized
```

**Possible Causes**:
- Incorrect credentials
- Account locked
- API permissions insufficient
- Token expired

**Resolution Steps**:
1. Verify credentials:
```bash
curl -u username:password https://your.jamfcloud.com/api/v1/auth/token
```

2. Check account status in Jamf Pro:
   - Settings → User Accounts and Groups
   - Verify account is active
   - Check "Jamf Pro Server Actions" privileges

3. Reset API account:
```bash
# Update password in Jamf Pro
# Update .env file
# Test authentication
python3 scripts/test_auth.py
```

#### Issue: GitHub Token Invalid
**Error Message**:
```
Error: Bad credentials
```

**Resolution**:
1. Generate new token:
   - GitHub → Settings → Developer settings → Personal access tokens
   - Create token with `repo` and `workflow` scopes

2. Update secret:
```bash
gh secret set GITHUB_TOKEN
```

### 2. Download Failures

#### Issue: Package Download Timeout
**Error Message**:
```
Error: Download timeout after 600 seconds
```

**Possible Causes**:
- Network congestion
- Large file size
- Vendor server issues

**Resolution**:
1. Increase timeout:
```python
# config/settings.py
DOWNLOAD_TIMEOUT = 1200  # 20 minutes
```

2. Use mirror/CDN:
```json
// config/applications.json
"download_url": "https://cdn.vendor.com/..."
```

3. Implement chunked download:
```python
downloader.use_chunks = True
downloader.chunk_size = 1024 * 1024  # 1MB chunks
```

#### Issue: SSL Certificate Verification Failed
**Error Message**:
```
SSL: CERTIFICATE_VERIFY_FAILED
```

**Resolution**:
1. Update certificates:
```bash
brew install ca-certificates
```

2. For testing only (NOT PRODUCTION):
```python
# Temporary workaround
import ssl
ssl._create_default_https_context = ssl._create_unverified_context
```

### 3. Package Processing Errors

#### Issue: Package Signature Verification Failed
**Error Message**:
```
Error: Package signature invalid or Team ID mismatch
```

**Resolution**:
1. Verify expected Team ID:
```bash
codesign -dvv /path/to/app.app 2>&1 | grep TeamIdentifier
```

2. Update configuration:
```json
"team_id": "CORRECT_ID"
```

3. Check package integrity:
```bash
pkgutil --check-signature package.pkg
```

#### Issue: DMG Mount Failed
**Error Message**:
```
Error: Failed to attach disk image
```

**Resolution**:
```bash
# Clean up orphaned mounts
hdiutil detach /Volumes/AppName -force

# Clear quarantine
xattr -d com.apple.quarantine file.dmg

# Retry mount
hdiutil attach file.dmg
```

### 4. Jamf Upload Issues

#### Issue: Package Already Exists
**Error Message**:
```
Error: Package with name already exists
```

**Resolution**:
1. Enable replacement:
```python
manager.upload_package(path, replace=True)
```

2. Or use versioned naming:
```python
package_name = f"{app_name}-{version}.pkg"
```

#### Issue: Distribution Point Unreachable
**Error Message**:
```
Error: Unable to connect to distribution point
```

**Resolution**:
1. Check JCDS status:
```bash
curl https://your.jcds.jamfcloud.com/health
```

2. Verify credentials:
   - Jamf Pro → Settings → File Share Distribution Points
   - Test connection

3. Use alternative upload method:
```python
manager.use_api_upload = True  # Instead of JCDS
```

### 5. Patch Management Errors

#### Issue: Patch Title Not Found
**Error Message**:
```
Error: Patch software title '1Password 8' not found
```

**Resolution**:
1. Create manually in Jamf Pro:
   - Settings → Computer Management → Patch Management
   - Add Software Title

2. Or use external source:
```python
manager.add_external_source("Jamf Patch")
```

#### Issue: Definition Already Exists
**Error Message**:
```
Error: Definition for version 8.10.45 already exists
```

**Resolution**:
```python
# Force update existing definition
manager.update_definition(title_id, version, force=True)
```

### 6. GitHub Actions Failures

#### Issue: Runner Offline
**Error Message**:
```
Error: No runners are available to run this job
```

**Resolution**:
1. Check runner status:
```bash
cd ~/actions-runner
./svc.sh status
```

2. Restart runner:
```bash
./svc.sh stop
./svc.sh start
```

3. Check logs:
```bash
tail -f _diag/Runner_*.log
```

#### Issue: Workflow Syntax Error
**Error Message**:
```
Error: .github/workflows/patch-update.yml: syntax error
```

**Resolution**:
1. Validate YAML:
```bash
yamllint .github/workflows/patch-update.yml
```

2. Use GitHub's workflow editor for validation

### 7. Performance Issues

#### Issue: Slow Package Processing
**Symptoms**: 
- Processing takes > 10 minutes per package
- High CPU/memory usage

**Resolution**:
1. Check system resources:
```bash
top -o cpu
df -h
```

2. Optimize processing:
```python
# Enable parallel processing
processor.parallel = True
processor.max_workers = 4
```

3. Clear temp files:
```bash
rm -rf /tmp/pkg_*
```

### 8. Smart Group Issues

#### Issue: Computers Not Appearing in Smart Group
**Symptoms**:
- Patch policy not deploying
- Smart group shows 0 members

**Resolution**:
1. Verify criteria:
```xml
<criteria>
  <criterion>
    <name>Application Title</name>
    <priority>0</priority>
    <and_or>and</and_or>
    <search_type>is</search_type>
    <value>1Password 7</value>
  </criterion>
</criteria>
```

2. Force recon:
```bash
sudo jamf recon
```

3. Check computer inventory

## Error Code Reference

| Code | Description | Resolution |
|------|-------------|------------|
| E001 | Authentication failed | Check credentials |
| E002 | Network timeout | Retry or increase timeout |
| E003 | Package corrupt | Re-download package |
| E004 | Signature invalid | Verify Team ID |
| E005 | API rate limit | Wait and retry |
| E006 | Disk space full | Clear cache/logs |
| E007 | Permission denied | Check file permissions |
| E008 | Version conflict | Resolve version mismatch |
| E009 | Policy creation failed | Check Jamf permissions |
| E010 | Runner offline | Restart runner service |

## Debug Commands

### Enable Verbose Logging
```bash
export LOG_LEVEL=DEBUG
python3 scripts/main_workflow.py --app "1password" --verbose
```

### Trace API Calls
```python
import logging
import http.client
http.client.HTTPConnection.debuglevel = 1
logging.basicConfig(level=logging.DEBUG)
```

### Profile Performance
```bash
python3 -m cProfile -o profile.stats scripts/main_workflow.py
python3 -m pstats profile.stats
```

### Memory Analysis
```python
from memory_profiler import profile

@profile
def process_package():
    # Function to analyze
    pass
```

## Log Analysis

### Find Errors
```bash
# Recent errors
grep -E "ERROR|CRITICAL" logs/*.log | tail -50

# Errors by component
grep ERROR logs/patch_management.log | cut -d' ' -f5- | sort | uniq -c

# Time-based analysis
awk '/ERROR/ {print $1, $2}' logs/*.log | sort | uniq -c
```

### Performance Metrics
```bash
# Download times
grep "Download completed" logs/*.log | awk '{print $NF}'

# API response times
grep "API call" logs/*.log | grep -o "[0-9.]*ms"
```

## Recovery Procedures

### Clear All Caches
```bash
#!/bin/bash
rm -rf cache/*
rm -rf /tmp/pkg_*
rm -rf ~/Library/Caches/patch-automation
echo "Caches cleared"
```

### Reset Configuration
```bash
#!/bin/bash
cp config/*.json config/backup/
git checkout -- config/
echo "Configuration reset to defaults"
```

### Force Stop All Processes
```bash
#!/bin/bash
pkill -f "patch_automation"
pkill -f "main_workflow"
./svc.sh stop
echo "All processes stopped"
```

## Useful Links & Documentation

### API Documentation
- [Jamf Pro API Reference](https://developer.jamf.com/jamf-pro/reference/jamf-pro-api)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [AutoPkg Wiki](https://github.com/autopkg/autopkg/wiki)

### Vendor Resources
- [1Password Admin Guide](https://support.1password.com/deploy-app/)
- [Chrome Enterprise Help](https://support.google.com/chrome/a/)
- [Microsoft AutoUpdate](https://docs.microsoft.com/en-us/deployoffice/mac/)

### Community Resources
- [MacAdmins Slack](https://macadmins.org/) - #jamf channel
- [Jamf Nation](https://community.jamf.com/)
- [AutoPkg Recipes](https://github.com/autopkg/autopkg-recipes)

## Emergency Contacts

| Service | Contact | Response Time |
|---------|---------|--------------|
| Jamf Support | support@jamf.com | 24 hours |
| GitHub Support | https://support.github.com | 48 hours |
| Internal IT | helpdesk@company.com | 1 hour |
| On-call Admin | +1-555-0100 | Immediate |