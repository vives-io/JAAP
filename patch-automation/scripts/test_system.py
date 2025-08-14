#!/usr/bin/env python3
"""
System Test Script
Validates the patch automation system components
"""

import os
import sys
import logging
from pathlib import Path
from typing import List, Dict

# Add current directory to path for imports
sys.path.append(str(Path(__file__).parent))

from application_registry import ApplicationRegistry
from package_downloader import PackageDownloader
from package_processor import PackageProcessor

def setup_test_logging():
    """Setup logging for tests"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

def test_application_registry() -> bool:
    """Test application registry"""
    print("🧪 Testing Application Registry...")
    
    try:
        registry = ApplicationRegistry()
        
        # Test loading applications
        apps = registry.get_supported_apps()
        if not apps:
            print("❌ No applications loaded")
            return False
        
        print(f"✅ Loaded {len(apps)} applications")
        
        # Test getting download info
        for app in apps[:3]:  # Test first 3 apps
            info = registry.get_download_info(app)
            if info:
                print(f"✅ Got download info for {app}")
            else:
                print(f"❌ No download info for {app}")
                
        return True
        
    except Exception as e:
        print(f"❌ Application registry test failed: {e}")
        return False

def test_package_downloader() -> bool:
    """Test package downloader (without actually downloading)"""
    print("🧪 Testing Package Downloader...")
    
    try:
        downloader = PackageDownloader(cache_dir="test_cache")
        
        # Test cache check (should return False for non-existent file)
        test_url = "https://example.com/test.dmg"
        is_cached, cache_path = downloader.check_cache(test_url, "test_app")
        
        if not is_cached:
            print("✅ Cache check working correctly")
        else:
            print("❌ Cache check returned unexpected result")
            return False
            
        # Test metrics
        metrics = downloader.get_metrics()
        if isinstance(metrics, dict):
            print("✅ Metrics collection working")
        else:
            print("❌ Metrics collection failed")
            return False
            
        return True
        
    except Exception as e:
        print(f"❌ Package downloader test failed: {e}")
        return False

def test_package_processor() -> bool:
    """Test package processor"""
    print("🧪 Testing Package Processor...")
    
    try:
        processor = PackageProcessor(working_dir="/tmp/test_processing")
        
        # Test Team ID validation
        team_ids = processor.team_ids
        if '1password' in team_ids and '2BUA8C4S2C' in team_ids['1password']:
            print("✅ Team ID configuration loaded")
        else:
            print("❌ Team ID configuration missing")
            return False
        
        # Test metadata extraction helpers
        archs = processor.get_architectures(Path("/usr/bin/python3"))
        if isinstance(archs, list):
            print("✅ Architecture detection working")
        else:
            print("❌ Architecture detection failed")
            
        return True
        
    except Exception as e:
        print(f"❌ Package processor test failed: {e}")
        return False

def test_configurations() -> bool:
    """Test configuration files"""
    print("🧪 Testing Configuration Files...")
    
    config_files = [
        "config/applications.yaml",
        "config/patch_cycles.yaml", 
        "config/workflow_config.yaml"
    ]
    
    all_good = True
    
    for config_file in config_files:
        config_path = Path(config_file)
        if config_path.exists():
            print(f"✅ {config_file} exists")
            
            # Try to load YAML
            try:
                import yaml
                with open(config_path, 'r') as f:
                    data = yaml.safe_load(f)
                    
                if data:
                    print(f"✅ {config_file} is valid YAML")
                else:
                    print(f"❌ {config_file} is empty")
                    all_good = False
                    
            except Exception as e:
                print(f"❌ {config_file} YAML error: {e}")
                all_good = False
        else:
            print(f"❌ {config_file} missing")
            all_good = False
    
    return all_good

def test_github_workflow() -> bool:
    """Test GitHub workflow file"""
    print("🧪 Testing GitHub Actions Workflow...")
    
    workflow_path = Path(".github/workflows/patch-update.yml")
    
    if not workflow_path.exists():
        print("❌ GitHub workflow file missing")
        return False
    
    print("✅ GitHub workflow file exists")
    
    # Basic YAML validation
    try:
        import yaml
        with open(workflow_path, 'r') as f:
            workflow = yaml.safe_load(f)
            
        # Check key components - 'on' becomes True in YAML parsing
        workflow_on = workflow.get('on', workflow.get(True, {}))
        if workflow_on and 'schedule' in workflow_on:
            print("✅ Workflow has schedule trigger")
        else:
            print("❌ Workflow missing schedule trigger")
            return False
            
        if 'jobs' in workflow and 'patch-update' in workflow['jobs']:
            print("✅ Workflow has patch-update job")
        else:
            print("❌ Workflow missing patch-update job")
            return False
            
        return True
        
    except Exception as e:
        print(f"❌ GitHub workflow validation failed: {e}")
        return False

def test_directory_structure() -> bool:
    """Test directory structure"""
    print("🧪 Testing Directory Structure...")
    
    required_dirs = [
        "scripts",
        "config", 
        "logs",
        "cache",
        "state",
        ".github/workflows",
        "setup"
    ]
    
    all_good = True
    
    for dir_path in required_dirs:
        if Path(dir_path).exists():
            print(f"✅ {dir_path}/ exists")
        else:
            print(f"❌ {dir_path}/ missing")
            all_good = False
    
    return all_good

def test_dependencies() -> bool:
    """Test Python dependencies"""
    print("🧪 Testing Python Dependencies...")
    
    required_modules = [
        'requests',
        'yaml',
        'dotenv',
        'xattr',
        'logging',
        'json',
        'pathlib'
    ]
    
    all_good = True
    
    for module in required_modules:
        try:
            if module == 'yaml':
                import yaml
            elif module == 'dotenv':
                from dotenv import load_dotenv
            elif module == 'xattr':
                import xattr
            else:
                __import__(module)
                
            print(f"✅ {module} available")
            
        except ImportError:
            print(f"❌ {module} not available")
            all_good = False
    
    return all_good

def run_system_tests() -> None:
    """Run all system tests"""
    print("🚀 Running Patch Automation System Tests")
    print("=" * 50)
    
    tests = [
        ("Directory Structure", test_directory_structure),
        ("Python Dependencies", test_dependencies),
        ("Configuration Files", test_configurations),
        ("Application Registry", test_application_registry),
        ("Package Downloader", test_package_downloader),
        ("Package Processor", test_package_processor),
        ("GitHub Workflow", test_github_workflow)
    ]
    
    results = []
    
    for test_name, test_func in tests:
        print(f"\n{test_name}")
        print("-" * len(test_name))
        
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} failed with exception: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 50)
    print("📊 Test Results Summary")
    print("=" * 50)
    
    passed = 0
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} {test_name}")
        if result:
            passed += 1
    
    print(f"\nPassed: {passed}/{total} ({passed/total*100:.1f}%)")
    
    if passed == total:
        print("\n🎉 All tests passed! System is ready for deployment.")
    else:
        print(f"\n⚠️  {total-passed} tests failed. Please address issues before deployment.")
        
    return passed == total

if __name__ == "__main__":
    setup_test_logging()
    
    # Change to project root directory
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)
    
    success = run_system_tests()
    sys.exit(0 if success else 1)