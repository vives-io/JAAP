#!/usr/bin/env python3
"""
Jamf Patch Management Integration
Handles all interactions with Jamf Pro API for patch management
"""

import requests
import json
import logging
import time
from typing import Dict, Optional, List, Tuple
from datetime import datetime
from pathlib import Path
import base64

class JamfPatchManager:
    """Main class for managing Jamf patch operations"""
    
    def __init__(self, jamf_url: str, username: str, password: str, title_editor_api_key: str = None):
        """
        Initialize Jamf Patch Manager
        
        Args:
            jamf_url: Jamf Pro server URL
            username: Jamf Pro username
            password: Jamf Pro password
            title_editor_api_key: Optional API key for Title Editor
        """
        self.jamf_url = jamf_url.rstrip('/')
        self.username = username
        self.password = password
        self.title_editor_api_key = title_editor_api_key
        self.session = requests.Session()
        self.token = None
        self.token_expiry = None
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        
        # API endpoints
        self.api_endpoints = {
            'auth': '/api/v1/auth/token',
            'patch_software_titles': '/api/v2/patch-software-titles',
            'patch_policies': '/api/v2/patch-policies',
            'packages': '/api/v1/packages',
            'computer_groups': '/api/v1/computer-groups',
            'patch_external_sources': '/api/v2/patch-external-sources'
        }
        
        # Authenticate
        self._authenticate()
    
    def _authenticate(self) -> None:
        """Authenticate with Jamf Pro and get bearer token"""
        try:
            auth_url = f"{self.jamf_url}{self.api_endpoints['auth']}"
            response = self.session.post(
                auth_url,
                auth=(self.username, self.password),
                headers={'Accept': 'application/json'}
            )
            response.raise_for_status()
            
            data = response.json()
            self.token = data['token']
            self.token_expiry = datetime.fromisoformat(data['expires'].replace('Z', '+00:00'))
            
            # Update session headers
            self.session.headers.update({
                'Authorization': f'Bearer {self.token}',
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            })
            
            self.logger.info("Successfully authenticated with Jamf Pro")
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Authentication failed: {e}")
            raise
    
    def _check_token(self) -> None:
        """Check if token is still valid and refresh if needed"""
        if not self.token or datetime.now() >= self.token_expiry:
            self.logger.info("Token expired, re-authenticating...")
            self._authenticate()
    
    def read_patch_title(self, software_title: str) -> Optional[Dict]:
        """
        Check if patch software title exists
        
        Args:
            software_title: Name of the software title
            
        Returns:
            Patch title data if exists, None otherwise
        """
        self._check_token()
        
        try:
            url = f"{self.jamf_url}{self.api_endpoints['patch_software_titles']}"
            params = {'filter': f'name=="{software_title}"'}
            
            response = self.session.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            if data.get('totalCount', 0) > 0:
                return data['results'][0]
            
            self.logger.info(f"Patch title '{software_title}' not found")
            return None
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Error reading patch title: {e}")
            raise
    
    def get_patch_title_configuration(self, title_id: str) -> Optional[Dict]:
        """
        Get detailed configuration for a patch title
        
        Args:
            title_id: Patch title ID
            
        Returns:
            Patch title configuration
        """
        self._check_token()
        
        try:
            url = f"{self.jamf_url}{self.api_endpoints['patch_software_titles']}/{title_id}"
            response = self.session.get(url)
            response.raise_for_status()
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Error getting patch title configuration: {e}")
            raise
    
    def check_patch_definition(self, title_id: str, version: str) -> Optional[Dict]:
        """
        Check if patch definition exists for a specific version
        
        Args:
            title_id: Patch title ID
            version: Software version
            
        Returns:
            Definition data if exists, None otherwise
        """
        self._check_token()
        
        try:
            config = self.get_patch_title_configuration(title_id)
            if not config:
                return None
            
            # Check if version exists in definitions
            for definition in config.get('definitions', []):
                if definition.get('version') == version:
                    return definition
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error checking patch definition: {e}")
            return None
    
    def create_update_definition(self, title_id: str, definition_data: Dict) -> bool:
        """
        Create or update patch definition via Title Editor API or Jamf API
        
        Args:
            title_id: Patch title ID
            definition_data: Definition data including version, minimumOperatingSystem, etc.
            
        Returns:
            True if successful, False otherwise
        """
        self._check_token()
        
        try:
            # First try to add definition through Jamf API
            url = f"{self.jamf_url}{self.api_endpoints['patch_software_titles']}/{title_id}/definitions"
            
            payload = {
                "version": definition_data['version'],
                "minimumOperatingSystem": definition_data.get('minimumOperatingSystem', '10.15'),
                "releaseDate": definition_data.get('releaseDate', datetime.now().isoformat()),
                "rebootRequired": definition_data.get('rebootRequired', False),
                "killApps": definition_data.get('killApps', []),
                "supplements": definition_data.get('supplements', []),
                "capabilities": definition_data.get('capabilities', [
                    {"key": "INSTALLER", "value": "PKG"}
                ])
            }
            
            response = self.session.post(url, json=payload)
            
            if response.status_code == 201:
                self.logger.info(f"Successfully created definition for version {definition_data['version']}")
                return True
            elif response.status_code == 409:
                # Definition already exists, try to update
                self.logger.info(f"Definition already exists for version {definition_data['version']}")
                return True
            else:
                self.logger.error(f"Failed to create definition: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Error creating/updating definition: {e}")
            return False
    
    def add_package_to_version(self, title_id: str, version: str, package_info: Dict) -> bool:
        """
        Add package to definition version
        
        Args:
            title_id: Patch title ID
            version: Software version
            package_info: Package information including ID and name
            
        Returns:
            True if successful, False otherwise
        """
        self._check_token()
        
        try:
            # Get current configuration
            config = self.get_patch_title_configuration(title_id)
            if not config:
                return False
            
            # Find the definition for this version
            definition_index = None
            for i, definition in enumerate(config.get('definitions', [])):
                if definition.get('version') == version:
                    definition_index = i
                    break
            
            if definition_index is None:
                self.logger.error(f"Definition not found for version {version}")
                return False
            
            # Update the definition with package info
            config['definitions'][definition_index]['package'] = {
                "id": package_info['id'],
                "name": package_info['name'],
                "displayName": package_info.get('displayName', package_info['name'])
            }
            
            # Update the patch title
            url = f"{self.jamf_url}{self.api_endpoints['patch_software_titles']}/{title_id}"
            response = self.session.put(url, json=config)
            
            if response.status_code == 200:
                self.logger.info(f"Successfully added package to version {version}")
                return True
            else:
                self.logger.error(f"Failed to add package: {response.text}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error adding package to version: {e}")
            return False
    
    def upload_package(self, package_path: str) -> Optional[Dict]:
        """
        Upload package to Jamf Pro
        
        Args:
            package_path: Path to the package file
            
        Returns:
            Package information if successful, None otherwise
        """
        self._check_token()
        
        try:
            package_path = Path(package_path)
            if not package_path.exists():
                self.logger.error(f"Package file not found: {package_path}")
                return None
            
            # Create package record first
            package_name = package_path.name
            url = f"{self.jamf_url}{self.api_endpoints['packages']}"
            
            package_data = {
                "name": package_name,
                "category": "Third Party Apps",
                "priority": 10,
                "fillUserTemplate": False,
                "fillExistingUsers": False,
                "osRequirements": "",
                "info": f"Uploaded by patch automation on {datetime.now().isoformat()}"
            }
            
            response = self.session.post(url, json=package_data)
            
            if response.status_code != 201:
                # Package might already exist, try to get it
                response = self.session.get(url, params={'filter': f'name=="{package_name}"'})
                if response.status_code == 200:
                    data = response.json()
                    if data.get('totalCount', 0) > 0:
                        package_info = data['results'][0]
                        self.logger.info(f"Package already exists: {package_name}")
                        return package_info
                
                self.logger.error(f"Failed to create package record: {response.text}")
                return None
            
            package_info = response.json()
            self.logger.info(f"Created package record: {package_name} (ID: {package_info['id']})")
            
            # Note: Actual file upload would require JCDS or file share access
            # This is a placeholder for the upload process
            self.logger.warning("Package file upload requires JCDS or file share configuration")
            
            return package_info
            
        except Exception as e:
            self.logger.error(f"Error uploading package: {e}")
            return None
    
    def create_patch_policy(self, policy_data: Dict) -> Optional[str]:
        """
        Create new patch policy with smart group scoping
        
        Args:
            policy_data: Policy configuration data
            
        Returns:
            Policy ID if successful, None otherwise
        """
        self._check_token()
        
        try:
            url = f"{self.jamf_url}{self.api_endpoints['patch_policies']}"
            
            # Build policy payload
            payload = {
                "enabled": policy_data.get('enabled', True),
                "targetPatchVersion": policy_data['version'],
                "name": policy_data['name'],
                "softwareTitleId": policy_data['softwareTitleId'],
                "releaseDate": policy_data.get('releaseDate', datetime.now().timestamp() * 1000),
                "incrementalUpdates": policy_data.get('incrementalUpdates', False),
                "rebootMinutes": policy_data.get('rebootMinutes', 0),
                "notificationSettings": {
                    "notificationType": policy_data.get('notificationType', 'SELF_SERVICE'),
                    "reminders": {
                        "frequency": policy_data.get('reminderFrequency', 1),
                        "enabled": policy_data.get('remindersEnabled', True)
                    }
                },
                "userInteraction": {
                    "messageStart": policy_data.get('messageStart', 'An update is available for this application.'),
                    "messageFinish": policy_data.get('messageFinish', 'Update complete.'),
                    "allowDeferral": policy_data.get('allowDeferral', True),
                    "deferralPeriod": policy_data.get('deferralPeriod', 7),
                    "deadlineEnabled": policy_data.get('deadlineEnabled', True),
                    "deadlinePeriod": policy_data.get('deadlinePeriod', 7)
                },
                "scope": {
                    "targets": {
                        "computerGroups": policy_data.get('computerGroups', []),
                        "computers": policy_data.get('computers', []),
                        "buildings": policy_data.get('buildings', []),
                        "departments": policy_data.get('departments', [])
                    },
                    "limitations": {
                        "networkSegments": policy_data.get('networkSegments', []),
                        "users": policy_data.get('limitUsers', []),
                        "userGroups": policy_data.get('limitUserGroups', [])
                    },
                    "exclusions": {
                        "computerGroups": policy_data.get('excludeComputerGroups', []),
                        "computers": policy_data.get('excludeComputers', []),
                        "buildings": policy_data.get('excludeBuildings', []),
                        "departments": policy_data.get('excludeDepartments', []),
                        "users": policy_data.get('excludeUsers', []),
                        "userGroups": policy_data.get('excludeUserGroups', [])
                    }
                }
            }
            
            response = self.session.post(url, json=payload)
            
            if response.status_code == 201:
                policy_id = response.json().get('id')
                self.logger.info(f"Successfully created patch policy: {policy_data['name']} (ID: {policy_id})")
                return policy_id
            else:
                self.logger.error(f"Failed to create patch policy: {response.text}")
                return None
                
        except Exception as e:
            self.logger.error(f"Error creating patch policy: {e}")
            return None
    
    def get_smart_group_id(self, group_name: str) -> Optional[str]:
        """
        Get smart group ID by name
        
        Args:
            group_name: Name of the smart group
            
        Returns:
            Group ID if found, None otherwise
        """
        self._check_token()
        
        try:
            url = f"{self.jamf_url}{self.api_endpoints['computer_groups']}"
            params = {'filter': f'name=="{group_name}"'}
            
            response = self.session.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            if data.get('totalCount', 0) > 0:
                return str(data['results'][0]['id'])
            
            self.logger.warning(f"Smart group not found: {group_name}")
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting smart group: {e}")
            return None
    
    def create_smart_group(self, group_data: Dict) -> Optional[str]:
        """
        Create a smart group if it doesn't exist
        
        Args:
            group_data: Smart group configuration
            
        Returns:
            Group ID if successful, None otherwise
        """
        self._check_token()
        
        # Check if group already exists
        existing_id = self.get_smart_group_id(group_data['name'])
        if existing_id:
            return existing_id
        
        try:
            url = f"{self.jamf_url}{self.api_endpoints['computer_groups']}"
            
            payload = {
                "name": group_data['name'],
                "isSmart": True,
                "criteria": group_data.get('criteria', []),
                "site": group_data.get('site', {"id": "-1", "name": "None"})
            }
            
            response = self.session.post(url, json=payload)
            
            if response.status_code == 201:
                group_id = response.json().get('id')
                self.logger.info(f"Created smart group: {group_data['name']} (ID: {group_id})")
                return str(group_id)
            else:
                self.logger.error(f"Failed to create smart group: {response.text}")
                return None
                
        except Exception as e:
            self.logger.error(f"Error creating smart group: {e}")
            return None
    
    def get_external_patch_sources(self) -> List[Dict]:
        """
        Get list of external patch sources
        
        Returns:
            List of external patch sources
        """
        self._check_token()
        
        try:
            url = f"{self.jamf_url}{self.api_endpoints['patch_external_sources']}"
            response = self.session.get(url)
            response.raise_for_status()
            
            data = response.json()
            return data.get('results', [])
            
        except Exception as e:
            self.logger.error(f"Error getting external patch sources: {e}")
            return []
    
    def close(self) -> None:
        """Close the session and cleanup"""
        if self.session:
            self.session.close()
        self.logger.info("Jamf Patch Manager session closed")


def setup_logging(log_level: str = 'INFO') -> None:
    """Setup logging configuration"""
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format=log_format,
        handlers=[
            logging.FileHandler('logs/patch_management.log'),
            logging.StreamHandler()
        ]
    )


if __name__ == "__main__":
    # Example usage
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    setup_logging()
    
    manager = JamfPatchManager(
        jamf_url=os.getenv('JAMF_URL'),
        username=os.getenv('JAMF_USERNAME'),
        password=os.getenv('JAMF_PASSWORD'),
        title_editor_api_key=os.getenv('TITLE_EDITOR_API_KEY')
    )
    
    # Example: Check for 1Password patch title
    title = manager.read_patch_title("1Password 8")
    if title:
        print(f"Found patch title: {title['name']} (ID: {title['id']})")
    
    manager.close()