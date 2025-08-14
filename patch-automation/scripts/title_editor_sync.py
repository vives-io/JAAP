#!/usr/bin/env python3
"""
Title Editor Sync Module
Manages patch definitions and keeps them synchronized
"""

import requests
import json
import logging
from typing import Dict, Optional, List
from datetime import datetime
from pathlib import Path

class TitleEditorSync:
    """Synchronize patch definitions with Title Editor"""
    
    def __init__(self, jamf_url: str, username: str, password: str,
                 title_editor_url: Optional[str] = None,
                 title_editor_token: Optional[str] = None):
        """
        Initialize Title Editor sync
        
        Args:
            jamf_url: Jamf Pro URL
            username: Jamf username
            password: Jamf password  
            title_editor_url: Optional Title Editor instance URL
            title_editor_token: Optional Title Editor API token
        """
        self.jamf_url = jamf_url.rstrip('/')
        self.username = username
        self.password = password
        self.title_editor_url = title_editor_url
        self.title_editor_token = title_editor_token
        
        self.session = requests.Session()
        self.logger = logging.getLogger(__name__)
        
        # Authenticate with Jamf
        self._authenticate_jamf()
        
        # If Title Editor credentials provided, set up headers
        if self.title_editor_url and self.title_editor_token:
            self.title_editor_headers = {
                'Authorization': f'Bearer {self.title_editor_token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
    
    def _authenticate_jamf(self) -> None:
        """Authenticate with Jamf Pro"""
        auth_url = f"{self.jamf_url}/api/v1/auth/token"
        
        try:
            response = self.session.post(
                auth_url,
                auth=(self.username, self.password)
            )
            response.raise_for_status()
            
            token_data = response.json()
            self.jamf_token = token_data['token']
            
            # Update session headers
            self.session.headers.update({
                'Authorization': f'Bearer {self.jamf_token}',
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            })
            
            self.logger.info("Authenticated with Jamf Pro")
            
        except Exception as e:
            self.logger.error(f"Jamf authentication failed: {e}")
            raise
    
    def get_patch_software_titles(self) -> List[Dict]:
        """
        Get all patch software titles from Jamf
        
        Returns:
            List of patch software titles
        """
        url = f"{self.jamf_url}/api/v2/patch-software-titles"
        
        try:
            response = self.session.get(url)
            response.raise_for_status()
            
            data = response.json()
            return data.get('results', [])
            
        except Exception as e:
            self.logger.error(f"Error getting patch titles: {e}")
            return []
    
    def get_patch_definitions(self, title_id: str) -> List[Dict]:
        """
        Get patch definitions for a software title
        
        Args:
            title_id: Patch software title ID
            
        Returns:
            List of patch definitions
        """
        url = f"{self.jamf_url}/api/v2/patch-software-titles/{title_id}"
        
        try:
            response = self.session.get(url)
            response.raise_for_status()
            
            data = response.json()
            return data.get('definitions', [])
            
        except Exception as e:
            self.logger.error(f"Error getting patch definitions: {e}")
            return []
    
    def check_version_exists(self, title_id: str, version: str) -> bool:
        """
        Check if a version already exists in patch definitions
        
        Args:
            title_id: Patch software title ID
            version: Version to check
            
        Returns:
            True if version exists
        """
        definitions = self.get_patch_definitions(title_id)
        
        for definition in definitions:
            if definition.get('version') == version:
                return True
        
        return False
    
    def create_patch_definition(self, title_id: str, version: str,
                              metadata: Dict) -> bool:
        """
        Create a new patch definition
        
        Args:
            title_id: Patch software title ID
            version: Version number
            metadata: Package metadata
            
        Returns:
            True if successful
        """
        # Check if version already exists
        if self.check_version_exists(title_id, version):
            self.logger.info(f"Version {version} already exists for title {title_id}")
            return True
        
        # If we have Title Editor access, use it
        if self.title_editor_url and self.title_editor_token:
            return self._create_via_title_editor(title_id, version, metadata)
        else:
            return self._create_via_jamf_api(title_id, version, metadata)
    
    def _create_via_title_editor(self, title_id: str, version: str,
                                metadata: Dict) -> bool:
        """
        Create definition via Title Editor API
        
        Args:
            title_id: Patch software title ID
            version: Version number
            metadata: Package metadata
            
        Returns:
            True if successful
        """
        url = f"{self.title_editor_url}/v2/titles/{title_id}/definitions"
        
        # Build definition payload
        payload = {
            "version": version,
            "releaseDate": datetime.now().isoformat(),
            "standalone": True,
            "minimumOperatingSystem": metadata.get('minimum_os', '10.15'),
            "rebootRequired": False,
            "killApps": self._get_kill_apps(metadata.get('bundle_id', '')),
            "components": [
                {
                    "name": metadata.get('name', 'Application'),
                    "version": version,
                    "criteria": [
                        {
                            "name": "Application Bundle ID",
                            "operator": "is",
                            "value": metadata.get('bundle_id', ''),
                            "type": "recon",
                            "and": True
                        }
                    ]
                }
            ],
            "capabilities": [
                {
                    "name": "Operating System Version",
                    "operator": "greater than or equal",
                    "value": metadata.get('minimum_os', '10.15'),
                    "type": "recon"
                }
            ],
            "dependencies": []
        }
        
        try:
            response = requests.post(
                url,
                json=payload,
                headers=self.title_editor_headers
            )
            
            if response.status_code in [200, 201]:
                self.logger.info(f"Created patch definition for version {version}")
                return True
            else:
                self.logger.error(f"Failed to create definition: {response.text}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error creating definition via Title Editor: {e}")
            return False
    
    def _create_via_jamf_api(self, title_id: str, version: str,
                            metadata: Dict) -> bool:
        """
        Create definition via Jamf API (limited functionality)
        
        Args:
            title_id: Patch software title ID
            version: Version number
            metadata: Package metadata
            
        Returns:
            True if successful
        """
        # Note: Direct creation via Jamf API is limited
        # This is a placeholder - typically requires Title Editor
        self.logger.warning(
            "Direct patch definition creation via Jamf API is limited. "
            "Consider using Title Editor for full functionality."
        )
        
        # Log for manual intervention
        self.logger.info(
            f"Manual action required: Create patch definition for {version} "
            f"in Jamf Pro > Patch Management > {title_id}"
        )
        
        return False
    
    def _get_kill_apps(self, bundle_id: str) -> List[Dict]:
        """
        Get kill apps configuration based on bundle ID
        
        Args:
            bundle_id: Application bundle ID
            
        Returns:
            List of apps to kill during update
        """
        # Common kill app configurations
        kill_apps_map = {
            'com.1password': [
                {"bundleId": "com.1password.1password"},
                {"bundleId": "com.1password.1password-launcher"}
            ],
            'com.google.Chrome': [
                {"bundleId": "com.google.Chrome"}
            ],
            'org.mozilla.firefox': [
                {"bundleId": "org.mozilla.firefox"}
            ],
            'com.tinyspeck.slackmacgap': [
                {"bundleId": "com.tinyspeck.slackmacgap"}
            ],
            'us.zoom.xos': [
                {"bundleId": "us.zoom.xos"}
            ],
            'com.microsoft': [
                {"bundleId": "com.microsoft.Word"},
                {"bundleId": "com.microsoft.Excel"},
                {"bundleId": "com.microsoft.Powerpoint"},
                {"bundleId": "com.microsoft.Outlook"},
                {"bundleId": "com.microsoft.onenote.mac"}
            ]
        }
        
        # Find matching configuration
        for key, apps in kill_apps_map.items():
            if key in bundle_id:
                return apps
        
        # Default: just the app itself
        return [{"bundleId": bundle_id}]
    
    def link_package_to_definition(self, title_id: str, version: str,
                                  package_id: str) -> bool:
        """
        Link a package to a patch definition version
        
        Args:
            title_id: Patch software title ID
            version: Version number
            package_id: Jamf package ID
            
        Returns:
            True if successful
        """
        url = f"{self.jamf_url}/api/v2/patch-software-titles/{title_id}"
        
        try:
            # Get current configuration
            response = self.session.get(url)
            response.raise_for_status()
            config = response.json()
            
            # Find the definition for this version
            definition_found = False
            for definition in config.get('definitions', []):
                if definition.get('version') == version:
                    # Add package reference
                    definition['package'] = {
                        "id": package_id,
                        "displayName": f"Package for {version}"
                    }
                    definition_found = True
                    break
            
            if not definition_found:
                self.logger.error(f"Definition not found for version {version}")
                return False
            
            # Update configuration
            response = self.session.put(url, json=config)
            
            if response.status_code == 200:
                self.logger.info(f"Linked package {package_id} to version {version}")
                return True
            else:
                self.logger.error(f"Failed to link package: {response.text}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error linking package: {e}")
            return False
    
    def sync_all_titles(self, definitions_file: str = "config/patch_definitions.json") -> Dict:
        """
        Sync all patch titles with local definitions
        
        Args:
            definitions_file: Path to local definitions file
            
        Returns:
            Sync results
        """
        results = {
            'synced': [],
            'failed': [],
            'skipped': []
        }
        
        # Load local definitions
        definitions_path = Path(definitions_file)
        if not definitions_path.exists():
            self.logger.warning(f"Definitions file not found: {definitions_file}")
            return results
        
        with open(definitions_path) as f:
            local_definitions = json.load(f)
        
        # Get all patch titles from Jamf
        titles = self.get_patch_software_titles()
        
        for title in titles:
            title_id = title['id']
            title_name = title['name']
            
            # Check if we have local definition
            if title_name not in local_definitions:
                results['skipped'].append(title_name)
                continue
            
            local_def = local_definitions[title_name]
            
            # Check each version
            for version_info in local_def.get('versions', []):
                version = version_info['version']
                
                if not self.check_version_exists(title_id, version):
                    # Create definition
                    if self.create_patch_definition(title_id, version, version_info):
                        results['synced'].append(f"{title_name} {version}")
                    else:
                        results['failed'].append(f"{title_name} {version}")
                else:
                    self.logger.info(f"Version {version} already exists for {title_name}")
        
        return results
    
    def get_latest_version(self, title_id: str) -> Optional[str]:
        """
        Get the latest version from patch definitions
        
        Args:
            title_id: Patch software title ID
            
        Returns:
            Latest version string or None
        """
        definitions = self.get_patch_definitions(title_id)
        
        if not definitions:
            return None
        
        # Sort by version (assuming semantic versioning)
        try:
            sorted_defs = sorted(
                definitions,
                key=lambda x: tuple(map(int, x['version'].split('.'))),
                reverse=True
            )
            
            return sorted_defs[0]['version'] if sorted_defs else None
            
        except Exception as e:
            self.logger.debug(f"Error sorting versions: {e}")
            # Fallback to string sorting
            sorted_defs = sorted(
                definitions,
                key=lambda x: x['version'],
                reverse=True
            )
            
            return sorted_defs[0]['version'] if sorted_defs else None


def setup_logging(log_level: str = 'INFO') -> None:
    """Setup logging configuration"""
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format=log_format,
        handlers=[
            logging.FileHandler('logs/title_editor_sync.log'),
            logging.StreamHandler()
        ]
    )


if __name__ == "__main__":
    import argparse
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    parser = argparse.ArgumentParser(description='Sync Title Editor definitions')
    parser.add_argument('--sync-all', action='store_true', 
                       help='Sync all definitions')
    parser.add_argument('--title', help='Specific title to sync')
    parser.add_argument('--version', help='Version to create')
    parser.add_argument('--verbose', action='store_true', help='Verbose logging')
    
    args = parser.parse_args()
    
    setup_logging('DEBUG' if args.verbose else 'INFO')
    
    sync = TitleEditorSync(
        jamf_url=os.getenv('JAMF_URL'),
        username=os.getenv('JAMF_USERNAME'),
        password=os.getenv('JAMF_PASSWORD'),
        title_editor_url=os.getenv('TITLE_EDITOR_URL'),
        title_editor_token=os.getenv('TITLE_EDITOR_TOKEN')
    )
    
    if args.sync_all:
        results = sync.sync_all_titles()
        print(json.dumps(results, indent=2))
    elif args.title and args.version:
        # Create specific definition
        success = sync.create_patch_definition(
            args.title,
            args.version,
            {}  # Would need metadata
        )
        print(f"Success: {success}")
    else:
        # List all titles
        titles = sync.get_patch_software_titles()
        for title in titles:
            print(f"{title['id']}: {title['name']}")
            latest = sync.get_latest_version(title['id'])
            if latest:
                print(f"  Latest version: {latest}")