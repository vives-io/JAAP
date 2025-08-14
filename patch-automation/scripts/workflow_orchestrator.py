#!/usr/bin/env python3
"""
Workflow Orchestrator with State Management
Main controller for the automated patching workflow
"""

import os
import json
import yaml
import logging
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum

# Import our modules
from package_downloader import PackageDownloader
from package_processor import PackageProcessor
from patch_management import JamfPatchManager
from title_editor_sync import TitleEditorSync
from application_registry import ApplicationRegistry

class WorkflowState(Enum):
    """Workflow execution states"""
    NOT_STARTED = "not_started"
    DOWNLOADING = "downloading"
    PROCESSING = "processing" 
    UPLOADING = "uploading"
    PATCH_MANAGEMENT = "patch_management"
    POLICY_CREATION = "policy_creation"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass
class ApplicationStatus:
    """Status tracking for individual application"""
    app_name: str
    state: WorkflowState = WorkflowState.NOT_STARTED
    download_path: Optional[str] = None
    processed_path: Optional[str] = None
    package_id: Optional[str] = None
    patch_title_id: Optional[str] = None
    version: Optional[str] = None
    error_message: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    retries: int = 0

@dataclass
class WorkflowStatus:
    """Overall workflow status"""
    workflow_id: str
    state: WorkflowState = WorkflowState.NOT_STARTED
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    applications: Dict[str, ApplicationStatus] = None
    dry_run: bool = False
    total_apps: int = 0
    completed_apps: int = 0
    failed_apps: int = 0
    metrics: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.applications is None:
            self.applications = {}
        if self.metrics is None:
            self.metrics = {}

class WorkflowOrchestrator:
    """Main workflow orchestrator with state management"""
    
    def __init__(self, config_dir: str = "config", state_dir: str = "state"):
        """
        Initialize workflow orchestrator
        
        Args:
            config_dir: Configuration directory
            state_dir: State persistence directory
        """
        self.config_dir = Path(config_dir)
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        
        # Load configuration
        self.workflow_config = self._load_config('workflow_config.yaml')
        self.patch_cycles_config = self._load_config('patch_cycles.yaml')
        
        # Initialize components
        self.registry = ApplicationRegistry(
            str(self.config_dir / 'applications.yaml')
        )
        self.downloader = PackageDownloader(
            cache_dir=self.workflow_config.get('cache', {}).get('cache_dir', 'cache'),
            max_workers=self.workflow_config.get('execution', {}).get('max_parallel_workers', 5)
        )
        self.processor = PackageProcessor()
        
        # Initialize Jamf components
        self._init_jamf_components()
        
        # Current workflow status
        self.current_workflow: Optional[WorkflowStatus] = None
        
        # Performance metrics
        self.metrics = {
            'total_runtime': 0,
            'download_time': 0,
            'processing_time': 0,
            'upload_time': 0,
            'cache_hits': 0,
            'cache_misses': 0
        }
    
    def _load_config(self, filename: str) -> Dict:
        """Load configuration file"""
        config_path = self.config_dir / filename
        if not config_path.exists():
            self.logger.warning(f"Configuration file not found: {filename}")
            return {}
        
        try:
            with open(config_path, 'r') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            self.logger.error(f"Error loading config {filename}: {e}")
            return {}
    
    def _init_jamf_components(self):
        """Initialize Jamf-related components"""
        try:
            jamf_url = os.getenv('JAMF_URL')
            jamf_username = os.getenv('JAMF_USERNAME')
            jamf_password = os.getenv('JAMF_PASSWORD')
            
            if not all([jamf_url, jamf_username, jamf_password]):
                raise ValueError("Missing required Jamf credentials")
            
            self.jamf_manager = JamfPatchManager(
                jamf_url=jamf_url,
                username=jamf_username,
                password=jamf_password,
                title_editor_api_key=os.getenv('TITLE_EDITOR_TOKEN')
            )
            
            # Initialize Title Editor sync if configured
            title_editor_url = os.getenv('TITLE_EDITOR_URL')
            title_editor_token = os.getenv('TITLE_EDITOR_TOKEN')
            
            if title_editor_url and title_editor_token:
                self.title_editor = TitleEditorSync(
                    jamf_url=jamf_url,
                    username=jamf_username,
                    password=jamf_password,
                    title_editor_url=title_editor_url,
                    title_editor_token=title_editor_token
                )
            else:
                self.title_editor = None
                
        except Exception as e:
            self.logger.error(f"Failed to initialize Jamf components: {e}")
            self.jamf_manager = None
            self.title_editor = None
    
    def create_workflow(self, app_names: List[str], cycle: Optional[str] = None,
                       dry_run: bool = False) -> str:
        """
        Create a new workflow
        
        Args:
            app_names: List of application names to process
            cycle: Patch cycle name (optional)
            dry_run: Whether to run in dry-run mode
            
        Returns:
            Workflow ID
        """
        workflow_id = f"workflow_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Resolve "all" to actual app names
        if len(app_names) == 1 and app_names[0].lower() == 'all':
            app_names = list(self.registry.get_supported_apps())
        
        # Create workflow status
        self.current_workflow = WorkflowStatus(
            workflow_id=workflow_id,
            start_time=datetime.now().isoformat(),
            applications={
                app_name: ApplicationStatus(app_name=app_name) 
                for app_name in app_names
            },
            dry_run=dry_run,
            total_apps=len(app_names)
        )
        
        self.logger.info(
            f"Created workflow {workflow_id} with {len(app_names)} applications "
            f"(dry_run: {dry_run})"
        )
        
        return workflow_id
    
    def run_workflow(self, app_names: List[str], cycle: Optional[str] = None,
                    dry_run: bool = False, force: bool = False) -> Dict:
        """
        Run the complete workflow
        
        Args:
            app_names: Applications to process
            cycle: Patch cycle
            dry_run: Dry run mode
            force: Force download even if cached
            
        Returns:
            Workflow results
        """
        workflow_start_time = datetime.now()
        
        try:
            # Create workflow
            workflow_id = self.create_workflow(app_names, cycle, dry_run)
            
            self.logger.info(f"Starting workflow {workflow_id}")
            self.current_workflow.state = WorkflowState.DOWNLOADING
            self._save_state()
            
            # Step 1: Download packages
            download_results = self._download_packages(force=force)
            
            # Step 2: Process packages
            self.current_workflow.state = WorkflowState.PROCESSING
            self._save_state()
            process_results = self._process_packages(download_results)
            
            # Step 3: Upload to Jamf (if not dry run)
            if not dry_run:
                self.current_workflow.state = WorkflowState.UPLOADING
                self._save_state()
                upload_results = self._upload_packages(process_results)
                
                # Step 4: Manage patch definitions
                self.current_workflow.state = WorkflowState.PATCH_MANAGEMENT
                self._save_state()
                patch_results = self._manage_patches(upload_results)
                
                # Step 5: Create/update policies
                self.current_workflow.state = WorkflowState.POLICY_CREATION
                self._save_state()
                policy_results = self._create_policies(patch_results, cycle)
            else:
                self.logger.info("Dry run mode - skipping upload and patch management")
                upload_results = {}
                patch_results = {}
                policy_results = {}
            
            # Complete workflow
            self.current_workflow.state = WorkflowState.COMPLETED
            self.current_workflow.end_time = datetime.now().isoformat()
            
            # Calculate completed/failed apps
            for app_status in self.current_workflow.applications.values():
                if app_status.state in [WorkflowState.COMPLETED]:
                    self.current_workflow.completed_apps += 1
                elif app_status.state == WorkflowState.FAILED:
                    self.current_workflow.failed_apps += 1
            
            # Record metrics
            total_runtime = (datetime.now() - workflow_start_time).total_seconds()
            self.current_workflow.metrics = {
                'total_runtime_seconds': total_runtime,
                'downloader_metrics': self.downloader.get_metrics(),
                'cache_stats': self._get_cache_stats(),
                'performance': self._get_performance_metrics()
            }
            
            self._save_state()
            
            self.logger.info(
                f"Workflow {workflow_id} completed: "
                f"{self.current_workflow.completed_apps} successful, "
                f"{self.current_workflow.failed_apps} failed"
            )
            
            return {
                'workflow_id': workflow_id,
                'status': 'completed',
                'completed_apps': self.current_workflow.completed_apps,
                'failed_apps': self.current_workflow.failed_apps,
                'runtime_seconds': total_runtime,
                'results': {
                    'downloads': download_results,
                    'processed': process_results,
                    'uploaded': upload_results if not dry_run else {},
                    'patches': patch_results if not dry_run else {},
                    'policies': policy_results if not dry_run else {}
                }
            }
            
        except Exception as e:
            self.logger.error(f"Workflow failed: {e}")
            self.logger.debug(traceback.format_exc())
            
            if self.current_workflow:
                self.current_workflow.state = WorkflowState.FAILED
                self.current_workflow.end_time = datetime.now().isoformat()
                self._save_state()
            
            return {
                'workflow_id': getattr(self.current_workflow, 'workflow_id', 'unknown'),
                'status': 'failed',
                'error': str(e),
                'runtime_seconds': (datetime.now() - workflow_start_time).total_seconds()
            }
    
    def _download_packages(self, force: bool = False) -> Dict[str, Path]:
        """Download packages for all applications"""
        self.logger.info("Starting package downloads")
        
        # Prepare download list
        downloads = []
        for app_name in self.current_workflow.applications.keys():
            app_status = self.current_workflow.applications[app_name]
            app_status.start_time = datetime.now().isoformat()
            
            download_info = self.registry.get_download_info(app_name)
            if download_info:
                downloads.append({
                    'name': app_name,
                    'url': download_info['url']
                })
            else:
                app_status.state = WorkflowState.FAILED
                app_status.error_message = "No download info available"
                self.logger.error(f"No download info for {app_name}")
        
        # Download packages in parallel
        results = self.downloader.download_parallel(downloads, force=force)
        
        # Update application statuses
        for app_name, download_path in results.items():
            app_status = self.current_workflow.applications[app_name]
            app_status.download_path = str(download_path)
            app_status.state = WorkflowState.PROCESSING
            
        return results
    
    def _process_packages(self, download_results: Dict[str, Path]) -> Dict[str, Dict]:
        """Process downloaded packages"""
        self.logger.info("Starting package processing")
        
        processed_results = {}
        
        for app_name, package_path in download_results.items():
            app_status = self.current_workflow.applications[app_name]
            
            try:
                # Get application config for Team ID
                app_config = self.registry.get_application(app_name)
                expected_team_id = app_config.get('team_id') if app_config else None
                
                # Process package
                metadata = self.processor.process_package(
                    package_path, 
                    app_name, 
                    expected_team_id
                )
                
                # Rename package if configured
                renamed_path = self.processor.rename_package(package_path, metadata)
                
                app_status.processed_path = str(renamed_path)
                app_status.version = metadata.get('version', 'unknown')
                app_status.state = WorkflowState.UPLOADING
                
                processed_results[app_name] = {
                    'path': renamed_path,
                    'metadata': metadata
                }
                
                self.logger.info(f"✓ Processed {app_name} v{metadata.get('version')}")
                
            except Exception as e:
                app_status.state = WorkflowState.FAILED
                app_status.error_message = str(e)
                app_status.end_time = datetime.now().isoformat()
                self.logger.error(f"✗ Failed to process {app_name}: {e}")
        
        return processed_results
    
    def _upload_packages(self, process_results: Dict[str, Dict]) -> Dict[str, str]:
        """Upload packages to Jamf"""
        self.logger.info("Starting package uploads")
        
        if not self.jamf_manager:
            self.logger.error("Jamf manager not initialized")
            return {}
        
        upload_results = {}
        
        for app_name, process_info in process_results.items():
            app_status = self.current_workflow.applications[app_name]
            
            try:
                package_path = process_info['path']
                metadata = process_info['metadata']
                
                # Upload package
                package_info = self.jamf_manager.upload_package(str(package_path))
                
                if package_info:
                    app_status.package_id = package_info.get('id')
                    app_status.state = WorkflowState.PATCH_MANAGEMENT
                    upload_results[app_name] = package_info['id']
                    
                    self.logger.info(f"✓ Uploaded {app_name} (Package ID: {package_info['id']})")
                else:
                    raise Exception("Upload failed - no package info returned")
                
            except Exception as e:
                app_status.state = WorkflowState.FAILED
                app_status.error_message = f"Upload failed: {str(e)}"
                app_status.end_time = datetime.now().isoformat()
                self.logger.error(f"✗ Failed to upload {app_name}: {e}")
        
        return upload_results
    
    def _manage_patches(self, upload_results: Dict[str, str]) -> Dict[str, str]:
        """Manage patch titles and definitions"""
        self.logger.info("Managing patch definitions")
        
        patch_results = {}
        
        for app_name, package_id in upload_results.items():
            app_status = self.current_workflow.applications[app_name]
            
            try:
                app_config = self.registry.get_application(app_name)
                patch_title_name = app_config.get('patch_title', app_name)
                
                # Check if patch title exists
                patch_title = self.jamf_manager.read_patch_title(patch_title_name)
                
                if not patch_title:
                    self.logger.warning(f"Patch title '{patch_title_name}' not found for {app_name}")
                    self.logger.info(f"Manual action required: Create patch title in Jamf Pro")
                    app_status.error_message = f"Patch title '{patch_title_name}' not found"
                    continue
                
                title_id = patch_title['id']
                app_status.patch_title_id = title_id
                
                # Create/update patch definition if Title Editor available
                if self.title_editor and app_status.version:
                    metadata = {
                        'name': app_config.get('name', app_name),
                        'bundle_id': app_config.get('bundle_id', ''),
                        'minimum_os': app_config.get('minimum_os', '10.15'),
                        'version': app_status.version
                    }
                    
                    if self.title_editor.create_patch_definition(
                        title_id, app_status.version, metadata
                    ):
                        self.logger.info(f"✓ Created/updated patch definition for {app_name}")
                
                # Link package to definition
                if self.jamf_manager.add_package_to_version(
                    title_id, app_status.version, {
                        'id': package_id,
                        'name': f"{app_name}-{app_status.version}"
                    }
                ):
                    app_status.state = WorkflowState.POLICY_CREATION
                    patch_results[app_name] = title_id
                    self.logger.info(f"✓ Linked package to {app_name} v{app_status.version}")
                
            except Exception as e:
                app_status.state = WorkflowState.FAILED
                app_status.error_message = f"Patch management failed: {str(e)}"
                app_status.end_time = datetime.now().isoformat()
                self.logger.error(f"✗ Patch management failed for {app_name}: {e}")
        
        return patch_results
    
    def _create_policies(self, patch_results: Dict[str, str], 
                        cycle: Optional[str] = None) -> Dict[str, str]:
        """Create patch policies"""
        self.logger.info("Creating patch policies")
        
        if not cycle:
            # Default to first cycle
            cycles = self.patch_cycles_config.get('cycles', [])
            cycle = cycles[0]['name'] if cycles else 'default'
        
        policy_results = {}
        
        for app_name, title_id in patch_results.items():
            app_status = self.current_workflow.applications[app_name]
            
            try:
                # Get cycle configuration
                cycle_config = None
                for c in self.patch_cycles_config.get('cycles', []):
                    if c['name'] == cycle:
                        cycle_config = c
                        break
                
                if not cycle_config:
                    raise Exception(f"Patch cycle '{cycle}' not found")
                
                # Get smart group ID
                smart_group_name = cycle_config['smart_group']
                smart_group_id = self.jamf_manager.get_smart_group_id(smart_group_name)
                
                if not smart_group_id:
                    raise Exception(f"Smart group '{smart_group_name}' not found")
                
                # Create policy
                policy_data = {
                    'name': f"Patch - {app_name} - {cycle}",
                    'version': app_status.version,
                    'softwareTitleId': title_id,
                    'computerGroups': [smart_group_id],
                    'userInteraction': cycle_config.get('user_interaction', {}),
                    'enabled': True
                }
                
                policy_id = self.jamf_manager.create_patch_policy(policy_data)
                
                if policy_id:
                    app_status.state = WorkflowState.COMPLETED
                    app_status.end_time = datetime.now().isoformat()
                    policy_results[app_name] = policy_id
                    
                    self.logger.info(f"✓ Created patch policy for {app_name} (ID: {policy_id})")
                else:
                    raise Exception("Policy creation failed")
                
            except Exception as e:
                app_status.state = WorkflowState.FAILED
                app_status.error_message = f"Policy creation failed: {str(e)}"
                app_status.end_time = datetime.now().isoformat()
                self.logger.error(f"✗ Failed to create policy for {app_name}: {e}")
        
        return policy_results
    
    def _save_state(self):
        """Save current workflow state"""
        if not self.current_workflow:
            return
        
        try:
            state_file = self.state_dir / f"{self.current_workflow.workflow_id}.json"
            
            # Convert to serializable format
            state_dict = asdict(self.current_workflow)
            
            # Convert ApplicationStatus objects
            applications_dict = {}
            for app_name, app_status in self.current_workflow.applications.items():
                applications_dict[app_name] = asdict(app_status)
                # Convert enum to string
                applications_dict[app_name]['state'] = app_status.state.value
            
            state_dict['applications'] = applications_dict
            state_dict['state'] = self.current_workflow.state.value
            
            with open(state_file, 'w') as f:
                json.dump(state_dict, f, indent=2)
                
        except Exception as e:
            self.logger.error(f"Failed to save state: {e}")
    
    def load_state(self, workflow_id: str) -> bool:
        """Load workflow state from file"""
        try:
            state_file = self.state_dir / f"{workflow_id}.json"
            
            if not state_file.exists():
                return False
            
            with open(state_file, 'r') as f:
                state_dict = json.load(f)
            
            # Reconstruct workflow status
            self.current_workflow = WorkflowStatus(
                workflow_id=state_dict['workflow_id'],
                state=WorkflowState(state_dict['state']),
                start_time=state_dict.get('start_time'),
                end_time=state_dict.get('end_time'),
                dry_run=state_dict.get('dry_run', False),
                total_apps=state_dict.get('total_apps', 0),
                completed_apps=state_dict.get('completed_apps', 0),
                failed_apps=state_dict.get('failed_apps', 0),
                metrics=state_dict.get('metrics', {})
            )
            
            # Reconstruct application statuses
            self.current_workflow.applications = {}
            for app_name, app_dict in state_dict.get('applications', {}).items():
                self.current_workflow.applications[app_name] = ApplicationStatus(
                    app_name=app_dict['app_name'],
                    state=WorkflowState(app_dict['state']),
                    download_path=app_dict.get('download_path'),
                    processed_path=app_dict.get('processed_path'),
                    package_id=app_dict.get('package_id'),
                    patch_title_id=app_dict.get('patch_title_id'),
                    version=app_dict.get('version'),
                    error_message=app_dict.get('error_message'),
                    start_time=app_dict.get('start_time'),
                    end_time=app_dict.get('end_time'),
                    retries=app_dict.get('retries', 0)
                )
            
            self.logger.info(f"Loaded workflow state: {workflow_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to load state: {e}")
            return False
    
    def get_workflow_status(self) -> Optional[Dict]:
        """Get current workflow status"""
        if not self.current_workflow:
            return None
        
        return {
            'workflow_id': self.current_workflow.workflow_id,
            'state': self.current_workflow.state.value,
            'start_time': self.current_workflow.start_time,
            'end_time': self.current_workflow.end_time,
            'dry_run': self.current_workflow.dry_run,
            'total_apps': self.current_workflow.total_apps,
            'completed_apps': self.current_workflow.completed_apps,
            'failed_apps': self.current_workflow.failed_apps,
            'applications': {
                name: {
                    'state': status.state.value,
                    'version': status.version,
                    'error': status.error_message
                }
                for name, status in self.current_workflow.applications.items()
            }
        }
    
    def _get_cache_stats(self) -> Dict:
        """Get cache statistics"""
        return {
            'cache_dir_size_mb': self._get_directory_size(self.downloader.cache_dir),
            'total_files': len(list(self.downloader.cache_dir.rglob('*'))),
        }
    
    def _get_performance_metrics(self) -> Dict:
        """Get performance metrics"""
        return {
            'memory_usage_mb': self._get_memory_usage(),
            'disk_usage_gb': self._get_disk_usage(),
        }
    
    def _get_directory_size(self, path: Path) -> float:
        """Get directory size in MB"""
        try:
            total = sum(f.stat().st_size for f in path.rglob('*') if f.is_file())
            return total / (1024 * 1024)
        except:
            return 0
    
    def _get_memory_usage(self) -> float:
        """Get current memory usage in MB"""
        try:
            import psutil
            process = psutil.Process()
            return process.memory_info().rss / (1024 * 1024)
        except:
            return 0
    
    def _get_disk_usage(self) -> float:
        """Get disk usage in GB"""
        try:
            import shutil
            _, _, free = shutil.disk_usage(Path.cwd())
            return free / (1024 * 1024 * 1024)
        except:
            return 0


def setup_logging(log_level: str = 'INFO') -> None:
    """Setup logging configuration"""
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format=log_format,
        handlers=[
            logging.FileHandler('logs/workflow_orchestrator.log'),
            logging.StreamHandler()
        ]
    )


if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv
    
    load_dotenv()
    
    parser = argparse.ArgumentParser(description='Workflow Orchestrator')
    parser.add_argument('--apps', nargs='+', required=True,
                       help='Applications to process (or "all")')
    parser.add_argument('--cycle', help='Patch cycle name')
    parser.add_argument('--dry-run', action='store_true', help='Dry run mode')
    parser.add_argument('--force', action='store_true', help='Force download')
    parser.add_argument('--resume', help='Resume workflow ID')
    parser.add_argument('--status', help='Show status of workflow ID')
    parser.add_argument('--verbose', action='store_true', help='Verbose logging')
    
    args = parser.parse_args()
    
    setup_logging('DEBUG' if args.verbose else 'INFO')
    
    orchestrator = WorkflowOrchestrator()
    
    if args.status:
        # Load and show status
        if orchestrator.load_state(args.status):
            status = orchestrator.get_workflow_status()
            print(json.dumps(status, indent=2))
        else:
            print(f"Workflow {args.status} not found")
    
    elif args.resume:
        # Resume workflow
        if orchestrator.load_state(args.resume):
            print(f"Resuming workflow {args.resume}")
            # Implementation for resume logic would go here
        else:
            print(f"Workflow {args.resume} not found")
    
    else:
        # Run new workflow
        results = orchestrator.run_workflow(
            app_names=args.apps,
            cycle=args.cycle,
            dry_run=args.dry_run,
            force=args.force
        )
        
        print(json.dumps(results, indent=2))