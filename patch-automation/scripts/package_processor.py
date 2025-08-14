#!/usr/bin/env python3
"""
Package Processor with verification and metadata extraction
Handles DMG, PKG, and ZIP files with Team ID verification
"""

import os
import json
import subprocess
import tempfile
import shutil
import plistlib
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple, List
from datetime import datetime

class PackageProcessor:
    """Process and verify downloaded packages"""
    
    def __init__(self, working_dir: str = "/tmp/package_processing"):
        """
        Initialize package processor
        
        Args:
            working_dir: Temporary directory for processing
        """
        self.working_dir = Path(working_dir)
        self.working_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        
        # Expected Team IDs for known vendors (Installomator pattern)
        self.team_ids = {
            '1password': ['2BUA8C4S2C'],
            'chrome': ['EQHXZ8M8AV'],
            'firefox': ['43AQ936H96'],
            'slack': ['BQR82RBBHL'],
            'zoom': ['BJ4HAAB9B3'],
            'microsoftoffice': ['UBF8T346G9'],
            'adobecreativecloud': ['JQ525L2MZD'],
            'docker': ['9BNSXJN65R'],
            'vscode': ['UBF8T346G9'],
            'notion': ['LBQJ5QBXR8']
        }
    
    def process_package(self, package_path: Path, app_name: str, 
                       expected_team_id: Optional[str] = None) -> Dict:
        """
        Process a package file and extract metadata
        
        Args:
            package_path: Path to package file
            app_name: Application name
            expected_team_id: Expected Team ID for verification
            
        Returns:
            Dictionary with package metadata
        """
        if not package_path.exists():
            raise FileNotFoundError(f"Package not found: {package_path}")
        
        # Determine package type
        file_ext = package_path.suffix.lower()
        
        if file_ext == '.dmg':
            return self.process_dmg(package_path, app_name, expected_team_id)
        elif file_ext == '.pkg':
            return self.process_pkg(package_path, app_name, expected_team_id)
        elif file_ext == '.zip':
            return self.process_zip(package_path, app_name, expected_team_id)
        else:
            raise ValueError(f"Unsupported package type: {file_ext}")
    
    def process_dmg(self, dmg_path: Path, app_name: str, 
                   expected_team_id: Optional[str] = None) -> Dict:
        """
        Process DMG file
        
        Args:
            dmg_path: Path to DMG file
            app_name: Application name
            expected_team_id: Expected Team ID
            
        Returns:
            Package metadata
        """
        mount_point = None
        
        try:
            # Mount DMG
            self.logger.info(f"Mounting {dmg_path.name}")
            mount_result = subprocess.run(
                ['hdiutil', 'attach', str(dmg_path), '-nobrowse', '-quiet'],
                capture_output=True,
                text=True
            )
            
            if mount_result.returncode != 0:
                raise Exception(f"Failed to mount DMG: {mount_result.stderr}")
            
            # Parse mount point from output
            for line in mount_result.stdout.splitlines():
                parts = line.split('\t')
                if len(parts) >= 3 and '/Volumes/' in parts[-1]:
                    mount_point = parts[-1].strip()
                    break
            
            if not mount_point:
                raise Exception("Could not determine mount point")
            
            self.logger.info(f"Mounted at {mount_point}")
            
            # Find app bundle
            app_path = None
            for item in Path(mount_point).iterdir():
                if item.suffix == '.app':
                    app_path = item
                    break
            
            if not app_path:
                raise Exception("No .app bundle found in DMG")
            
            # Extract metadata
            metadata = self.extract_app_metadata(app_path)
            
            # Verify Team ID
            if expected_team_id or app_name.lower() in self.team_ids:
                expected = expected_team_id or self.team_ids[app_name.lower()][0]
                if not self.verify_team_id(app_path, expected):
                    raise Exception(f"Team ID verification failed for {app_name}")
            
            # Add package info
            metadata['package_type'] = 'dmg'
            metadata['package_path'] = str(dmg_path)
            metadata['package_size'] = dmg_path.stat().st_size
            
            return metadata
            
        finally:
            # Always unmount
            if mount_point:
                self.logger.info(f"Unmounting {mount_point}")
                subprocess.run(
                    ['hdiutil', 'detach', mount_point, '-quiet'],
                    capture_output=True
                )
    
    def process_pkg(self, pkg_path: Path, app_name: str,
                   expected_team_id: Optional[str] = None) -> Dict:
        """
        Process PKG file
        
        Args:
            pkg_path: Path to PKG file
            app_name: Application name
            expected_team_id: Expected Team ID
            
        Returns:
            Package metadata
        """
        metadata = {
            'package_type': 'pkg',
            'package_path': str(pkg_path),
            'package_size': pkg_path.stat().st_size
        }
        
        try:
            # Check PKG signature
            self.logger.info(f"Checking signature for {pkg_path.name}")
            sig_result = subprocess.run(
                ['pkgutil', '--check-signature', str(pkg_path)],
                capture_output=True,
                text=True
            )
            
            if sig_result.returncode == 0:
                # Parse signature info
                for line in sig_result.stdout.splitlines():
                    if 'Developer ID Installer:' in line:
                        metadata['developer'] = line.split(':', 1)[1].strip()
                    elif 'Certificate Chain:' in line:
                        metadata['signed'] = True
            
            # Extract PKG info
            self.logger.info(f"Extracting PKG info for {pkg_path.name}")
            
            # Expand PKG to get Info.plist
            with tempfile.TemporaryDirectory() as temp_dir:
                expand_result = subprocess.run(
                    ['pkgutil', '--expand', str(pkg_path), temp_dir],
                    capture_output=True,
                    text=True
                )
                
                if expand_result.returncode == 0:
                    # Look for PackageInfo or Info.plist
                    for root, dirs, files in os.walk(temp_dir):
                        if 'PackageInfo' in files:
                            pkg_info_path = Path(root) / 'PackageInfo'
                            # Parse PackageInfo XML
                            import xml.etree.ElementTree as ET
                            tree = ET.parse(pkg_info_path)
                            root_elem = tree.getroot()
                            
                            metadata['bundle_id'] = root_elem.get('identifier', '')
                            metadata['version'] = root_elem.get('version', '')
                            
                        elif 'Info.plist' in files:
                            info_path = Path(root) / 'Info.plist'
                            with open(info_path, 'rb') as f:
                                plist = plistlib.load(f)
                                metadata['bundle_id'] = plist.get('CFBundleIdentifier', '')
                                metadata['version'] = plist.get('CFBundleShortVersionString', '')
            
            # Verify Team ID if provided
            if expected_team_id or app_name.lower() in self.team_ids:
                expected = expected_team_id or self.team_ids[app_name.lower()][0]
                team_id = self.extract_team_id_from_pkg(pkg_path)
                if team_id != expected:
                    raise Exception(f"Team ID mismatch: expected {expected}, got {team_id}")
                metadata['team_id'] = team_id
            
        except Exception as e:
            self.logger.warning(f"Error processing PKG: {e}")
        
        return metadata
    
    def process_zip(self, zip_path: Path, app_name: str,
                   expected_team_id: Optional[str] = None) -> Dict:
        """
        Process ZIP file
        
        Args:
            zip_path: Path to ZIP file
            app_name: Application name
            expected_team_id: Expected Team ID
            
        Returns:
            Package metadata
        """
        metadata = {
            'package_type': 'zip',
            'package_path': str(zip_path),
            'package_size': zip_path.stat().st_size
        }
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # Extract ZIP
            self.logger.info(f"Extracting {zip_path.name}")
            extract_result = subprocess.run(
                ['unzip', '-q', str(zip_path), '-d', temp_dir],
                capture_output=True,
                text=True
            )
            
            if extract_result.returncode != 0:
                raise Exception(f"Failed to extract ZIP: {extract_result.stderr}")
            
            # Find app bundle
            app_path = None
            for root, dirs, files in os.walk(temp_dir):
                for dir_name in dirs:
                    if dir_name.endswith('.app'):
                        app_path = Path(root) / dir_name
                        break
                if app_path:
                    break
            
            if app_path:
                # Extract metadata from app
                app_metadata = self.extract_app_metadata(app_path)
                metadata.update(app_metadata)
                
                # Verify Team ID
                if expected_team_id or app_name.lower() in self.team_ids:
                    expected = expected_team_id or self.team_ids[app_name.lower()][0]
                    if not self.verify_team_id(app_path, expected):
                        raise Exception(f"Team ID verification failed for {app_name}")
        
        return metadata
    
    def extract_app_metadata(self, app_path: Path) -> Dict:
        """
        Extract metadata from app bundle
        
        Args:
            app_path: Path to .app bundle
            
        Returns:
            App metadata dictionary
        """
        metadata = {}
        
        # Read Info.plist
        info_plist_path = app_path / 'Contents' / 'Info.plist'
        if info_plist_path.exists():
            try:
                with open(info_plist_path, 'rb') as f:
                    plist = plistlib.load(f)
                
                metadata['bundle_id'] = plist.get('CFBundleIdentifier', '')
                metadata['version'] = plist.get('CFBundleShortVersionString', '')
                metadata['build'] = plist.get('CFBundleVersion', '')
                metadata['name'] = plist.get('CFBundleName', app_path.stem)
                metadata['minimum_os'] = plist.get('LSMinimumSystemVersion', '')
                
                # Check architecture support
                executable_archs = plist.get('CFBundleExecutable', '')
                if executable_archs:
                    exec_path = app_path / 'Contents' / 'MacOS' / executable_archs
                    if exec_path.exists():
                        metadata['architectures'] = self.get_architectures(exec_path)
                
            except Exception as e:
                self.logger.warning(f"Error reading Info.plist: {e}")
        
        # Get code signature info
        try:
            metadata['team_id'] = self.get_team_id(app_path)
            metadata['signed'] = True
        except:
            metadata['signed'] = False
        
        return metadata
    
    def get_architectures(self, executable_path: Path) -> List[str]:
        """
        Get supported architectures from executable
        
        Args:
            executable_path: Path to executable
            
        Returns:
            List of architectures
        """
        try:
            result = subprocess.run(
                ['lipo', '-info', str(executable_path)],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                # Parse output like "Architectures in the fat file: ... are: x86_64 arm64"
                if 'are:' in result.stdout:
                    archs = result.stdout.split('are:')[1].strip().split()
                    return archs
        except Exception as e:
            self.logger.debug(f"Error getting architectures: {e}")
        
        return []
    
    def get_team_id(self, app_path: Path) -> Optional[str]:
        """
        Extract Team ID from app bundle
        
        Args:
            app_path: Path to .app bundle
            
        Returns:
            Team ID or None
        """
        try:
            result = subprocess.run(
                ['codesign', '-dv', '--verbose=4', str(app_path)],
                capture_output=True,
                text=True
            )
            
            # Team ID is in stderr
            for line in result.stderr.splitlines():
                if 'TeamIdentifier=' in line:
                    return line.split('=')[1].strip()
        
        except Exception as e:
            self.logger.debug(f"Error getting Team ID: {e}")
        
        return None
    
    def verify_team_id(self, app_path: Path, expected_team_id: str) -> bool:
        """
        Verify Team ID matches expected value
        
        Args:
            app_path: Path to app bundle
            expected_team_id: Expected Team ID
            
        Returns:
            True if Team ID matches
        """
        actual_team_id = self.get_team_id(app_path)
        
        if actual_team_id == expected_team_id:
            self.logger.info(f"✓ Team ID verified: {actual_team_id}")
            return True
        else:
            self.logger.error(
                f"✗ Team ID mismatch: expected {expected_team_id}, got {actual_team_id}"
            )
            return False
    
    def extract_team_id_from_pkg(self, pkg_path: Path) -> Optional[str]:
        """
        Extract Team ID from PKG signature
        
        Args:
            pkg_path: Path to PKG file
            
        Returns:
            Team ID or None
        """
        try:
            result = subprocess.run(
                ['pkgutil', '--check-signature', str(pkg_path)],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    # Look for line like "1. Developer ID Installer: Company (TEAMID)"
                    if 'Developer ID' in line and '(' in line and ')' in line:
                        # Extract Team ID from parentheses
                        start = line.rfind('(')
                        end = line.rfind(')')
                        if start < end:
                            return line[start+1:end]
        
        except Exception as e:
            self.logger.debug(f"Error extracting Team ID from PKG: {e}")
        
        return None
    
    def rename_package(self, package_path: Path, metadata: Dict, 
                      naming_pattern: str = "{name}-{version}.{ext}") -> Path:
        """
        Rename package according to naming convention
        
        Args:
            package_path: Current package path
            metadata: Package metadata
            naming_pattern: Naming pattern with placeholders
            
        Returns:
            New package path
        """
        # Extract values for naming
        name = metadata.get('name', 'Unknown').replace(' ', '')
        version = metadata.get('version', 'Unknown')
        ext = package_path.suffix[1:]  # Remove the dot
        
        # Generate new name
        new_name = naming_pattern.format(
            name=name,
            version=version,
            ext=ext
        )
        
        # Sanitize filename
        new_name = "".join(c for c in new_name if c.isalnum() or c in '.-_')
        
        new_path = package_path.parent / new_name
        
        # Rename if different
        if new_path != package_path:
            if new_path.exists():
                self.logger.warning(f"Target already exists: {new_name}")
                # Add timestamp to make unique
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                new_name = f"{new_path.stem}_{timestamp}{new_path.suffix}"
                new_path = package_path.parent / new_name
            
            package_path.rename(new_path)
            self.logger.info(f"Renamed package to: {new_name}")
            return new_path
        
        return package_path
    
    def repackage_as_pkg(self, app_path: Path, output_dir: Path, 
                        metadata: Dict) -> Optional[Path]:
        """
        Repackage an app bundle as a PKG (if needed)
        
        Args:
            app_path: Path to .app bundle
            output_dir: Output directory for PKG
            metadata: App metadata
            
        Returns:
            Path to created PKG or None
        """
        try:
            # Generate PKG name
            pkg_name = f"{metadata.get('name', 'App')}-{metadata.get('version', '1.0')}.pkg"
            pkg_path = output_dir / pkg_name
            
            # Build PKG using pkgbuild
            self.logger.info(f"Building PKG: {pkg_name}")
            
            result = subprocess.run([
                'pkgbuild',
                '--root', str(app_path.parent),
                '--identifier', metadata.get('bundle_id', 'com.example.app'),
                '--version', metadata.get('version', '1.0'),
                '--install-location', '/Applications',
                str(pkg_path)
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                self.logger.info(f"✓ Created PKG: {pkg_name}")
                return pkg_path
            else:
                self.logger.error(f"PKG creation failed: {result.stderr}")
                
        except Exception as e:
            self.logger.error(f"Error creating PKG: {e}")
        
        return None


def setup_logging(log_level: str = 'INFO') -> None:
    """Setup logging configuration"""
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format=log_format,
        handlers=[
            logging.FileHandler('logs/package_processor.log'),
            logging.StreamHandler()
        ]
    )


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Process package files')
    parser.add_argument('package', help='Path to package file')
    parser.add_argument('--app', required=True, help='Application name')
    parser.add_argument('--team-id', help='Expected Team ID')
    parser.add_argument('--rename', action='store_true', help='Rename package')
    parser.add_argument('--verbose', action='store_true', help='Verbose logging')
    
    args = parser.parse_args()
    
    setup_logging('DEBUG' if args.verbose else 'INFO')
    
    processor = PackageProcessor()
    
    try:
        # Process package
        metadata = processor.process_package(
            Path(args.package),
            args.app,
            args.team_id
        )
        
        print(json.dumps(metadata, indent=2))
        
        # Rename if requested
        if args.rename:
            new_path = processor.rename_package(Path(args.package), metadata)
            print(f"Renamed to: {new_path}")
            
    except Exception as e:
        print(f"Error: {e}")
        exit(1)