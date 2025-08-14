#!/usr/bin/env python3
"""
Application Registry with Installomator-style labels
Manages application configurations and download handlers
"""

import os
import yaml
import json
import re
import logging
import requests
from pathlib import Path
from typing import Dict, Optional, List
from urllib.parse import urljoin, urlparse
from datetime import datetime

class ApplicationRegistry:
    """Registry for managing application configurations"""
    
    def __init__(self, config_file: str = "config/applications.yaml"):
        """
        Initialize application registry
        
        Args:
            config_file: Path to applications configuration file
        """
        self.config_file = Path(config_file)
        self.logger = logging.getLogger(__name__)
        
        # Load applications configuration
        self.applications = self._load_applications()
        
        # Architecture detection
        self.arch = self._detect_architecture()
        
        # Session for web requests
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
    
    def _load_applications(self) -> Dict:
        """Load applications from configuration file"""
        if not self.config_file.exists():
            self.logger.warning(f"Configuration file not found: {self.config_file}")
            return {}
        
        try:
            with open(self.config_file, 'r') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            self.logger.error(f"Error loading configuration: {e}")
            return {}
    
    def _detect_architecture(self) -> str:
        """Detect system architecture"""
        import platform
        machine = platform.machine().lower()
        
        if machine == 'arm64':
            return 'arm64'
        else:
            return 'x86_64'
    
    def get_application(self, app_name: str) -> Optional[Dict]:
        """
        Get application configuration by name
        
        Args:
            app_name: Application name/label
            
        Returns:
            Application configuration or None
        """
        return self.applications.get(app_name.lower())
    
    def get_all_applications(self) -> Dict:
        """Get all application configurations"""
        return self.applications
    
    def get_download_info(self, app_name: str) -> Optional[Dict]:
        """
        Get download information for an application
        
        Args:
            app_name: Application name/label
            
        Returns:
            Dictionary with download URL and metadata
        """
        app_config = self.get_application(app_name)
        if not app_config:
            return None
        
        # Get handler based on download type
        download_type = app_config.get('download_type', 'direct')
        
        if download_type == 'direct':
            return self._handle_direct_download(app_config)
        elif download_type == 'github':
            return self._handle_github_releases(app_config)
        elif download_type == 'sparkle':
            return self._handle_sparkle_feed(app_config)
        elif download_type == 'json_api':
            return self._handle_json_api(app_config)
        elif download_type == 'web_scraper':
            return self._handle_web_scraper(app_config)
        else:
            self.logger.error(f"Unknown download type: {download_type}")
            return None
    
    def _handle_direct_download(self, config: Dict) -> Dict:
        """Handle direct download URL"""
        download_url = config.get('download_url')
        
        # Support architecture-specific URLs
        if self.arch == 'arm64' and config.get('download_url_arm64'):
            download_url = config['download_url_arm64']
        
        return {
            'url': download_url,
            'version': config.get('version', 'latest'),
            'filename': config.get('filename', ''),
            'type': config.get('package_type', 'dmg')
        }
    
    def _handle_github_releases(self, config: Dict) -> Optional[Dict]:
        """Handle GitHub releases API"""
        repo = config.get('github_repo')
        if not repo:
            return None
        
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"
        
        try:
            response = self.session.get(api_url)
            response.raise_for_status()
            
            release_data = response.json()
            version = release_data['tag_name'].lstrip('v')
            
            # Find appropriate asset
            for asset in release_data['assets']:
                asset_name = asset['name'].lower()
                
                # Filter by architecture if needed
                if self.arch == 'arm64':
                    if any(term in asset_name for term in ['arm64', 'apple', 'm1']):
                        download_url = asset['browser_download_url']
                        break
                else:
                    if any(term in asset_name for term in ['x86_64', 'intel', 'x64']):
                        download_url = asset['browser_download_url']
                        break
                    elif not any(term in asset_name for term in ['arm64', 'apple', 'm1']):
                        # Default to first suitable asset
                        download_url = asset['browser_download_url']
                        break
            else:
                # Fallback to first asset
                if release_data['assets']:
                    download_url = release_data['assets'][0]['browser_download_url']
                else:
                    return None
            
            return {
                'url': download_url,
                'version': version,
                'filename': download_url.split('/')[-1],
                'type': self._guess_package_type(download_url)
            }
            
        except Exception as e:
            self.logger.error(f"Error fetching GitHub release: {e}")
            return None
    
    def _handle_sparkle_feed(self, config: Dict) -> Optional[Dict]:
        """Handle Sparkle update feed"""
        feed_url = config.get('sparkle_feed_url')
        if not feed_url:
            return None
        
        try:
            response = self.session.get(feed_url)
            response.raise_for_status()
            
            # Parse XML (simplified)
            import xml.etree.ElementTree as ET
            root = ET.fromstring(response.text)
            
            # Find latest item
            latest_item = None
            latest_version = "0.0.0"
            
            for item in root.findall('.//item'):
                version_elem = item.find('sparkle:version', 
                                       {'sparkle': 'http://www.andymatuschak.org/xml-namespaces/sparkle'})
                if version_elem is not None:
                    version = version_elem.text
                    if self._compare_versions(version, latest_version) > 0:
                        latest_version = version
                        latest_item = item
            
            if latest_item:
                enclosure = latest_item.find('enclosure')
                if enclosure is not None:
                    download_url = enclosure.get('url')
                    return {
                        'url': download_url,
                        'version': latest_version,
                        'filename': download_url.split('/')[-1],
                        'type': self._guess_package_type(download_url)
                    }
            
        except Exception as e:
            self.logger.error(f"Error parsing Sparkle feed: {e}")
        
        return None
    
    def _handle_json_api(self, config: Dict) -> Optional[Dict]:
        """Handle JSON API endpoint"""
        api_url = config.get('api_url')
        if not api_url:
            return None
        
        try:
            response = self.session.get(api_url)
            response.raise_for_status()
            
            data = response.json()
            
            # Extract data using JSONPath-style selectors
            version = self._extract_json_value(data, config.get('version_selector', 'version'))
            download_url = self._extract_json_value(data, config.get('url_selector', 'download_url'))
            
            if download_url and version:
                return {
                    'url': download_url,
                    'version': version,
                    'filename': download_url.split('/')[-1],
                    'type': self._guess_package_type(download_url)
                }
            
        except Exception as e:
            self.logger.error(f"Error fetching JSON API: {e}")
        
        return None
    
    def _handle_web_scraper(self, config: Dict) -> Optional[Dict]:
        """Handle web scraping for download info"""
        scrape_url = config.get('scrape_url')
        if not scrape_url:
            return None
        
        try:
            response = self.session.get(scrape_url)
            response.raise_for_status()
            
            html_content = response.text
            
            # Extract download URL using regex
            url_pattern = config.get('url_pattern', '')
            if url_pattern:
                url_match = re.search(url_pattern, html_content)
                if url_match:
                    download_url = url_match.group(1)
                    
                    # Make relative URLs absolute
                    if not download_url.startswith('http'):
                        download_url = urljoin(scrape_url, download_url)
                    
                    # Extract version if pattern provided
                    version = 'latest'
                    version_pattern = config.get('version_pattern', '')
                    if version_pattern:
                        version_match = re.search(version_pattern, html_content)
                        if version_match:
                            version = version_match.group(1)
                    
                    return {
                        'url': download_url,
                        'version': version,
                        'filename': download_url.split('/')[-1],
                        'type': self._guess_package_type(download_url)
                    }
            
        except Exception as e:
            self.logger.error(f"Error scraping web page: {e}")
        
        return None
    
    def _extract_json_value(self, data: Dict, selector: str):
        """Extract value from JSON using dot notation"""
        keys = selector.split('.')
        current = data
        
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            elif isinstance(current, list) and key.isdigit():
                index = int(key)
                if 0 <= index < len(current):
                    current = current[index]
                else:
                    return None
            else:
                return None
        
        return current
    
    def _guess_package_type(self, url: str) -> str:
        """Guess package type from URL"""
        url_lower = url.lower()
        
        if url_lower.endswith('.dmg'):
            return 'dmg'
        elif url_lower.endswith('.pkg'):
            return 'pkg'
        elif url_lower.endswith('.zip'):
            return 'zip'
        else:
            return 'unknown'
    
    def _compare_versions(self, v1: str, v2: str) -> int:
        """Compare two version strings"""
        try:
            # Parse version parts
            def parse_version(version):
                return [int(x) for x in version.split('.')]
            
            parts1 = parse_version(v1)
            parts2 = parse_version(v2)
            
            # Pad shorter version with zeros
            max_len = max(len(parts1), len(parts2))
            parts1.extend([0] * (max_len - len(parts1)))
            parts2.extend([0] * (max_len - len(parts2)))
            
            # Compare parts
            for p1, p2 in zip(parts1, parts2):
                if p1 < p2:
                    return -1
                elif p1 > p2:
                    return 1
            
            return 0
            
        except Exception:
            # Fallback to string comparison
            if v1 < v2:
                return -1
            elif v1 > v2:
                return 1
            else:
                return 0
    
    def validate_application(self, app_name: str) -> List[str]:
        """
        Validate application configuration
        
        Args:
            app_name: Application name
            
        Returns:
            List of validation errors
        """
        errors = []
        app_config = self.get_application(app_name)
        
        if not app_config:
            errors.append(f"Application '{app_name}' not found")
            return errors
        
        # Required fields
        required_fields = ['name', 'bundle_id', 'team_id']
        for field in required_fields:
            if field not in app_config:
                errors.append(f"Missing required field: {field}")
        
        # Download configuration
        download_type = app_config.get('download_type', 'direct')
        if download_type == 'direct':
            if 'download_url' not in app_config:
                errors.append("Missing download_url for direct download")
        elif download_type == 'github':
            if 'github_repo' not in app_config:
                errors.append("Missing github_repo for GitHub releases")
        elif download_type == 'sparkle':
            if 'sparkle_feed_url' not in app_config:
                errors.append("Missing sparkle_feed_url for Sparkle feed")
        
        return errors
    
    def add_application(self, app_name: str, config: Dict) -> bool:
        """
        Add new application to registry
        
        Args:
            app_name: Application name
            config: Application configuration
            
        Returns:
            True if successful
        """
        try:
            self.applications[app_name.lower()] = config
            
            # Save to file
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, 'w') as f:
                yaml.dump(self.applications, f, default_flow_style=False)
            
            self.logger.info(f"Added application: {app_name}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error adding application: {e}")
            return False
    
    def get_supported_apps(self) -> List[str]:
        """Get list of supported application names"""
        return list(self.applications.keys())
    
    def search_applications(self, query: str) -> List[str]:
        """Search applications by name or bundle ID"""
        query_lower = query.lower()
        matches = []
        
        for app_name, config in self.applications.items():
            if (query_lower in app_name.lower() or 
                query_lower in config.get('name', '').lower() or
                query_lower in config.get('bundle_id', '').lower()):
                matches.append(app_name)
        
        return matches


def create_default_config() -> Dict:
    """Create default application configuration"""
    return {
        '1password': {
            'name': '1Password 8',
            'bundle_id': 'com.1password.1password',
            'team_id': '2BUA8C4S2C',
            'download_type': 'direct',
            'download_url': 'https://downloads.1password.com/mac/1Password.pkg',
            'package_type': 'pkg',
            'patch_title': '1Password 8'
        },
        'chrome': {
            'name': 'Google Chrome',
            'bundle_id': 'com.google.Chrome',
            'team_id': 'EQHXZ8M8AV',
            'download_type': 'direct',
            'download_url': 'https://dl.google.com/chrome/mac/stable/GGRO/googlechrome.dmg',
            'package_type': 'dmg',
            'patch_title': 'Google Chrome'
        },
        'firefox': {
            'name': 'Mozilla Firefox',
            'bundle_id': 'org.mozilla.firefox',
            'team_id': '43AQ936H96',
            'download_type': 'direct',
            'download_url': 'https://download.mozilla.org/?product=firefox-latest&os=osx&lang=en-US',
            'package_type': 'dmg',
            'patch_title': 'Mozilla Firefox'
        },
        'slack': {
            'name': 'Slack',
            'bundle_id': 'com.tinyspeck.slackmacgap',
            'team_id': 'BQR82RBBHL',
            'download_type': 'direct',
            'download_url': 'https://slack.com/ssb/download-osx-silicon',
            'download_url_x86_64': 'https://slack.com/ssb/download-osx',
            'package_type': 'dmg',
            'patch_title': 'Slack'
        },
        'zoom': {
            'name': 'Zoom',
            'bundle_id': 'us.zoom.xos',
            'team_id': 'BJ4HAAB9B3',
            'download_type': 'direct',
            'download_url': 'https://zoom.us/client/latest/ZoomInstaller.pkg',
            'package_type': 'pkg',
            'patch_title': 'Zoom'
        },
        'docker': {
            'name': 'Docker Desktop',
            'bundle_id': 'com.docker.docker',
            'team_id': '9BNSXJN65R',
            'download_type': 'direct',
            'download_url': 'https://desktop.docker.com/mac/main/arm64/Docker.dmg',
            'download_url_x86_64': 'https://desktop.docker.com/mac/main/amd64/Docker.dmg',
            'package_type': 'dmg',
            'patch_title': 'Docker Desktop'
        },
        'vscode': {
            'name': 'Visual Studio Code',
            'bundle_id': 'com.microsoft.VSCode',
            'team_id': 'UBF8T346G9',
            'download_type': 'github',
            'github_repo': 'microsoft/vscode',
            'package_type': 'zip',
            'patch_title': 'Microsoft Visual Studio Code'
        }
    }


def setup_logging(log_level: str = 'INFO') -> None:
    """Setup logging configuration"""
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format=log_format,
        handlers=[
            logging.FileHandler('logs/application_registry.log'),
            logging.StreamHandler()
        ]
    )


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Application Registry Management')
    parser.add_argument('--list', action='store_true', help='List all applications')
    parser.add_argument('--info', help='Show info for specific application')
    parser.add_argument('--download-info', help='Get download info for application')
    parser.add_argument('--validate', help='Validate application configuration')
    parser.add_argument('--create-default', action='store_true', 
                       help='Create default configuration file')
    parser.add_argument('--verbose', action='store_true', help='Verbose logging')
    
    args = parser.parse_args()
    
    setup_logging('DEBUG' if args.verbose else 'INFO')
    
    # Create default config if requested
    if args.create_default:
        config_file = Path("config/applications.yaml")
        config_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(config_file, 'w') as f:
            yaml.dump(create_default_config(), f, default_flow_style=False)
        
        print(f"Created default configuration: {config_file}")
        exit(0)
    
    registry = ApplicationRegistry()
    
    if args.list:
        print("Supported applications:")
        for app_name in registry.get_supported_apps():
            config = registry.get_application(app_name)
            print(f"  {app_name}: {config.get('name', 'Unknown')}")
    
    elif args.info:
        config = registry.get_application(args.info)
        if config:
            print(json.dumps(config, indent=2))
        else:
            print(f"Application '{args.info}' not found")
    
    elif args.download_info:
        info = registry.get_download_info(args.download_info)
        if info:
            print(json.dumps(info, indent=2))
        else:
            print(f"Could not get download info for '{args.download_info}'")
    
    elif args.validate:
        errors = registry.validate_application(args.validate)
        if errors:
            print(f"Validation errors for '{args.validate}':")
            for error in errors:
                print(f"  - {error}")
        else:
            print(f"Application '{args.validate}' is valid")
    
    else:
        parser.print_help()