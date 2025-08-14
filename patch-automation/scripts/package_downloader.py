#!/usr/bin/env python3
"""
Enhanced Package Downloader with intelligent caching
Incorporates patterns from AutoPkg's URLDownloader
"""

import os
import json
import hashlib
import logging
import requests
import subprocess
import tempfile
import time
import xattr
from pathlib import Path
from typing import Dict, Optional, Tuple, List
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, unquote

class PackageDownloader:
    """Advanced package downloader with caching and parallel processing"""
    
    def __init__(self, cache_dir: str = "cache", max_workers: int = 5):
        """
        Initialize downloader with cache directory and worker pool
        
        Args:
            cache_dir: Directory for caching downloads
            max_workers: Maximum parallel download workers
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_workers = max_workers
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'PatchAutomation/1.0 (Macintosh; Intel Mac OS X)'
        })
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        
        # Retry configuration
        self.max_retries = 3
        self.retry_delay = 1  # Start with 1 second
        self.timeout = 600  # 10 minutes default
        
        # Cache metadata attributes (AutoPkg pattern)
        self.XATTR_ETAG = "com.github.autopkg.etag"
        self.XATTR_LAST_MODIFIED = "com.github.autopkg.last-modified"
        self.XATTR_DOWNLOAD_URL = "com.github.autopkg.download-url"
        
        # Performance metrics
        self.metrics = {
            'cache_hits': 0,
            'cache_misses': 0,
            'download_times': [],
            'total_bytes': 0
        }
    
    def get_cached_info(self, filepath: Path) -> Dict[str, str]:
        """
        Get cached metadata from file extended attributes
        
        Args:
            filepath: Path to cached file
            
        Returns:
            Dictionary with cached metadata
        """
        info = {}
        
        if not filepath.exists():
            return info
        
        try:
            # Read xattr metadata (AutoPkg pattern)
            for attr_name, key in [
                (self.XATTR_ETAG, 'etag'),
                (self.XATTR_LAST_MODIFIED, 'last_modified'),
                (self.XATTR_DOWNLOAD_URL, 'url')
            ]:
                try:
                    value = xattr.getxattr(str(filepath), attr_name)
                    info[key] = value.decode('utf-8')
                except (OSError, IOError):
                    pass
                    
        except Exception as e:
            self.logger.debug(f"Error reading xattr from {filepath}: {e}")
        
        return info
    
    def set_cached_info(self, filepath: Path, info: Dict[str, str]) -> None:
        """
        Set cached metadata in file extended attributes
        
        Args:
            filepath: Path to cached file
            info: Metadata to cache
        """
        try:
            # Set xattr metadata (AutoPkg pattern)
            for key, attr_name in [
                ('etag', self.XATTR_ETAG),
                ('last_modified', self.XATTR_LAST_MODIFIED),
                ('url', self.XATTR_DOWNLOAD_URL)
            ]:
                if key in info and info[key]:
                    xattr.setxattr(
                        str(filepath),
                        attr_name,
                        info[key].encode('utf-8')
                    )
        except Exception as e:
            self.logger.warning(f"Error setting xattr on {filepath}: {e}")
    
    def check_cache(self, url: str, app_name: str) -> Tuple[bool, Optional[Path]]:
        """
        Check if we have a valid cached version
        
        Args:
            url: Download URL
            app_name: Application name
            
        Returns:
            Tuple of (is_cached, filepath)
        """
        # Generate cache filename
        cache_file = self.cache_dir / app_name / self._get_filename_from_url(url)
        
        if not cache_file.exists():
            return False, None
        
        # Get cached metadata
        cached_info = self.get_cached_info(cache_file)
        
        if not cached_info:
            return False, cache_file
        
        # Check if URL changed
        if cached_info.get('url') != url:
            self.logger.info(f"URL changed for {app_name}, invalidating cache")
            return False, cache_file
        
        # Make HEAD request to check if file changed
        try:
            response = self.session.head(url, timeout=30)
            response.raise_for_status()
            
            # Check ETag
            current_etag = response.headers.get('ETag', '').strip('"')
            cached_etag = cached_info.get('etag', '').strip('"')
            
            if current_etag and cached_etag and current_etag == cached_etag:
                self.logger.info(f"Cache hit for {app_name} (ETag match)")
                self.metrics['cache_hits'] += 1
                return True, cache_file
            
            # Check Last-Modified
            current_modified = response.headers.get('Last-Modified')
            cached_modified = cached_info.get('last_modified')
            
            if current_modified and cached_modified and current_modified == cached_modified:
                self.logger.info(f"Cache hit for {app_name} (Last-Modified match)")
                self.metrics['cache_hits'] += 1
                return True, cache_file
            
            # Check Content-Length as fallback
            current_size = response.headers.get('Content-Length')
            if current_size and cache_file.stat().st_size == int(current_size):
                self.logger.info(f"Cache hit for {app_name} (size match)")
                self.metrics['cache_hits'] += 1
                return True, cache_file
                
        except Exception as e:
            self.logger.debug(f"Cache check failed for {app_name}: {e}")
        
        self.metrics['cache_misses'] += 1
        return False, cache_file
    
    def _get_filename_from_url(self, url: str) -> str:
        """
        Extract filename from URL or generate one
        
        Args:
            url: Download URL
            
        Returns:
            Filename for the download
        """
        parsed = urlparse(url)
        filename = unquote(os.path.basename(parsed.path))
        
        if not filename or filename == '/':
            # Generate filename from URL
            filename = hashlib.md5(url.encode()).hexdigest()[:8] + '.download'
        
        return filename
    
    def _download_with_retry(self, url: str, dest_path: Path, app_name: str) -> bool:
        """
        Download file with exponential backoff retry
        
        Args:
            url: Download URL
            dest_path: Destination file path
            app_name: Application name for logging
            
        Returns:
            True if successful
        """
        attempt = 0
        delay = self.retry_delay
        
        while attempt < self.max_retries:
            try:
                attempt += 1
                self.logger.info(f"Downloading {app_name} (attempt {attempt}/{self.max_retries})")
                
                start_time = time.time()
                
                # Use curl for download (more reliable than requests for large files)
                # Following AutoPkg's URLDownloader pattern
                curl_cmd = [
                    '/usr/bin/curl',
                    '--location',  # Follow redirects
                    '--fail',  # Fail on HTTP errors
                    '--silent',
                    '--show-error',
                    '--speed-time', '30',  # Timeout if speed is too slow
                    '--speed-limit', '1024',  # Minimum 1KB/s
                    '--connect-timeout', '30',
                    '--max-time', str(self.timeout),
                    '--dump-header', f'{dest_path}.headers',
                    '--output', str(dest_path),
                    '--write-out', '%{http_code}|%{size_download}|%{time_total}',
                    url
                ]
                
                # Create parent directory
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Run curl
                result = subprocess.run(
                    curl_cmd,
                    capture_output=True,
                    text=True
                )
                
                if result.returncode == 0:
                    # Parse curl output
                    output_parts = result.stdout.strip().split('|')
                    if len(output_parts) >= 3:
                        http_code = output_parts[0]
                        size_downloaded = int(output_parts[1])
                        time_total = float(output_parts[2])
                        
                        self.metrics['total_bytes'] += size_downloaded
                        self.metrics['download_times'].append(time_total)
                        
                        # Parse headers and set xattr
                        headers_file = Path(f'{dest_path}.headers')
                        if headers_file.exists():
                            headers = self._parse_headers_file(headers_file)
                            
                            # Set extended attributes
                            info = {
                                'etag': headers.get('etag', '').strip('"'),
                                'last_modified': headers.get('last-modified', ''),
                                'url': url
                            }
                            self.set_cached_info(dest_path, info)
                            
                            # Clean up headers file
                            headers_file.unlink()
                        
                        download_time = time.time() - start_time
                        speed = size_downloaded / (1024 * 1024 * download_time)  # MB/s
                        
                        self.logger.info(
                            f"Downloaded {app_name}: {size_downloaded/(1024*1024):.2f}MB "
                            f"in {download_time:.2f}s ({speed:.2f}MB/s)"
                        )
                        
                        return True
                    
                # Download failed
                error_msg = result.stderr.strip() if result.stderr else f"HTTP {result.stdout}"
                self.logger.warning(f"Download failed for {app_name}: {error_msg}")
                
                # Clean up partial download
                if dest_path.exists():
                    dest_path.unlink()
                
            except Exception as e:
                self.logger.error(f"Download error for {app_name}: {e}")
            
            if attempt < self.max_retries:
                self.logger.info(f"Retrying in {delay} seconds...")
                time.sleep(delay)
                delay *= 2  # Exponential backoff
        
        return False
    
    def _parse_headers_file(self, headers_file: Path) -> Dict[str, str]:
        """
        Parse HTTP headers from curl dump-header file
        
        Args:
            headers_file: Path to headers file
            
        Returns:
            Dictionary of headers
        """
        headers = {}
        
        try:
            with open(headers_file, 'r') as f:
                for line in f:
                    if ':' in line:
                        key, value = line.split(':', 1)
                        headers[key.strip().lower()] = value.strip()
        except Exception as e:
            self.logger.debug(f"Error parsing headers: {e}")
        
        return headers
    
    def download(self, url: str, app_name: str, force: bool = False) -> Optional[Path]:
        """
        Download a package with caching
        
        Args:
            url: Download URL
            app_name: Application name
            force: Force download even if cached
            
        Returns:
            Path to downloaded file or None if failed
        """
        # Check cache first
        if not force:
            is_cached, cache_file = self.check_cache(url, app_name)
            if is_cached and cache_file and cache_file.exists():
                self.logger.info(f"Using cached package for {app_name}")
                return cache_file
        
        # Prepare download path
        app_cache_dir = self.cache_dir / app_name
        app_cache_dir.mkdir(parents=True, exist_ok=True)
        
        filename = self._get_filename_from_url(url)
        dest_path = app_cache_dir / filename
        
        # Download with retry
        if self._download_with_retry(url, dest_path, app_name):
            return dest_path
        
        self.logger.error(f"Failed to download {app_name} after {self.max_retries} attempts")
        return None
    
    def download_parallel(self, downloads: List[Dict[str, str]], force: bool = False) -> Dict[str, Path]:
        """
        Download multiple packages in parallel
        
        Args:
            downloads: List of dicts with 'url' and 'name' keys
            force: Force download even if cached
            
        Returns:
            Dictionary mapping app names to download paths
        """
        results = {}
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all downloads
            future_to_app = {
                executor.submit(self.download, d['url'], d['name'], force): d['name']
                for d in downloads
            }
            
            # Process completed downloads
            for future in as_completed(future_to_app):
                app_name = future_to_app[future]
                try:
                    result = future.result()
                    if result:
                        results[app_name] = result
                        self.logger.info(f"✓ {app_name} downloaded successfully")
                    else:
                        self.logger.error(f"✗ {app_name} download failed")
                except Exception as e:
                    self.logger.error(f"✗ {app_name} download error: {e}")
        
        return results
    
    def get_metrics(self) -> Dict:
        """
        Get download metrics
        
        Returns:
            Dictionary of performance metrics
        """
        total_time = sum(self.metrics['download_times'])
        avg_time = total_time / len(self.metrics['download_times']) if self.metrics['download_times'] else 0
        
        cache_total = self.metrics['cache_hits'] + self.metrics['cache_misses']
        cache_rate = (self.metrics['cache_hits'] / cache_total * 100) if cache_total > 0 else 0
        
        return {
            'cache_hit_rate': f"{cache_rate:.1f}%",
            'total_downloads': self.metrics['cache_misses'],
            'total_cache_hits': self.metrics['cache_hits'],
            'total_bytes': f"{self.metrics['total_bytes'] / (1024*1024*1024):.2f} GB",
            'average_download_time': f"{avg_time:.2f}s"
        }
    
    def cleanup_old_cache(self, days: int = 30) -> int:
        """
        Clean up cache files older than specified days
        
        Args:
            days: Age threshold in days
            
        Returns:
            Number of files cleaned
        """
        cleaned = 0
        cutoff_time = time.time() - (days * 24 * 3600)
        
        for app_dir in self.cache_dir.iterdir():
            if app_dir.is_dir():
                for cache_file in app_dir.iterdir():
                    if cache_file.stat().st_mtime < cutoff_time:
                        cache_file.unlink()
                        cleaned += 1
                        self.logger.info(f"Cleaned old cache: {cache_file.name}")
        
        return cleaned


def setup_logging(log_level: str = 'INFO') -> None:
    """Setup logging configuration"""
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format=log_format,
        handlers=[
            logging.FileHandler('logs/package_downloader.log'),
            logging.StreamHandler()
        ]
    )


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Download packages with caching')
    parser.add_argument('--app', required=True, help='Application name')
    parser.add_argument('--url', required=True, help='Download URL')
    parser.add_argument('--force', action='store_true', help='Force download')
    parser.add_argument('--verbose', action='store_true', help='Verbose logging')
    
    args = parser.parse_args()
    
    setup_logging('DEBUG' if args.verbose else 'INFO')
    
    downloader = PackageDownloader()
    result = downloader.download(args.url, args.app, args.force)
    
    if result:
        print(f"Downloaded to: {result}")
        print(f"Metrics: {json.dumps(downloader.get_metrics(), indent=2)}")
    else:
        print("Download failed")
        exit(1)