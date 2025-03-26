#!/usr/bin/env python
# -*- coding: utf-8 -*-

'''
Tencent Cloud Object Storage (COS) utility functions
'''

import os
import logging
from typing import List, Optional, Union, Dict, Any
from qcloud_cos import CosConfig, CosS3Client
from qcloud_cos.cos_exception import CosServiceError, CosClientError

logger = logging.getLogger(__name__)

# Default bucket name
DEFAULT_BUCKET = 'wx-records-1347723456'
# Default region
DEFAULT_REGION = 'ap-guangzhou'  # Change this to your actual region


class TencentCosClient:
    """Wrapper class for Tencent Cloud Object Storage operations"""
    
    def __init__(self, 
                 secret_id: str = None, 
                 secret_key: str = None, 
                 region: str = DEFAULT_REGION,
                 bucket: str = DEFAULT_BUCKET,
                 token: str = None,
                 scheme: str = 'https'):
        """
        Initialize the Tencent COS client.
        
        Args:
            secret_id: Tencent Cloud API Secret ID (if None, will try to get from env variables)
            secret_key: Tencent Cloud API Secret Key (if None, will try to get from env variables)
            region: COS bucket region, default is 'ap-guangzhou'
            bucket: COS bucket name, default is 'wx-records-1347723456'
            token: Temporary token for temporary credentials, default is None
            scheme: Protocol used (http/https), default is 'https'
        """
        # Try to get credentials from environment variables if not provided
        if not secret_id:
            secret_id = Variable.get('TENCENT_SECRET_ID')
        if not secret_key:
            secret_key = Variable.get('TENCENT_SECRET_KEY')
        
        if not secret_id or not secret_key:
            raise ValueError("Tencent Cloud credentials not provided and not found in environment variables")
        
        # Initialize COS configuration
        self.config = CosConfig(
            Region=region,
            SecretId=secret_id,
            SecretKey=secret_key,
            Token=token,
            Scheme=scheme
        )
        
        # Initialize the COS client
        self.client = CosS3Client(self.config)
        
        # Set the bucket name
        self.bucket = bucket
        self.region = region
    
    def upload_file(self, 
                   local_path: str, 
                   cos_path: str = None, 
                   bucket: str = None,
                   **kwargs) -> Dict[str, Any]:
        """
        Upload a local file to COS.
        
        Args:
            local_path: Path to the local file to upload
            cos_path: Path in COS where the file will be stored. If None, will use filename from local_path
            bucket: Bucket name (optional, uses instance default if not specified)
            **kwargs: Additional parameters to pass to the COS client
            
        Returns:
            Response dictionary from COS API
        """
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"Local file not found: {local_path}")
        
        # Use filename from local path if cos_path not provided
        if not cos_path:
            cos_path = os.path.basename(local_path)
        
        # Remove leading slash if present
        if cos_path.startswith('/'):
            cos_path = cos_path[1:]
        
        bucket_name = bucket or self.bucket
        
        try:
            response = self.client.upload_file(
                Bucket=bucket_name,
                LocalFilePath=local_path,
                Key=cos_path,
                **kwargs
            )
            logger.info(f"Uploaded {local_path} to cos://{bucket_name}/{cos_path}")
            return response
        except (CosServiceError, CosClientError) as e:
            logger.error(f"Failed to upload file to COS: {str(e)}")
            raise
    
    def download_file(self, 
                     cos_path: str, 
                     local_path: str,
                     bucket: str = None,
                     **kwargs) -> Dict[str, Any]:
        """
        Download a file from COS to local storage.
        
        Args:
            cos_path: Path of the file in COS
            local_path: Local path where the file will be saved
            bucket: Bucket name (optional, uses instance default if not specified)
            **kwargs: Additional parameters to pass to the COS client
            
        Returns:
            Response dictionary from COS API
        """
        # Remove leading slash if present
        if cos_path.startswith('/'):
            cos_path = cos_path[1:]
        
        bucket_name = bucket or self.bucket
        
        # Ensure the directory exists
        os.makedirs(os.path.dirname(os.path.abspath(local_path)), exist_ok=True)
        
        try:
            response = self.client.download_file(
                Bucket=bucket_name,
                Key=cos_path,
                DestFilePath=local_path,
                **kwargs
            )
            logger.info(f"Downloaded cos://{bucket_name}/{cos_path} to {local_path}")
            return response
        except (CosServiceError, CosClientError) as e:
            logger.error(f"Failed to download file from COS: {str(e)}")
            raise
    
    def list_objects(self, 
                     prefix: str = '',
                     delimiter: str = '/',
                     bucket: str = None,
                     max_keys: int = 1000) -> Dict[str, Any]:
        """
        List objects in the COS bucket.
        
        Args:
            prefix: Prefix to filter objects
            delimiter: Delimiter for hierarchy (e.g., '/' for folder-like structure)
            bucket: Bucket name (optional, uses instance default if not specified)
            max_keys: Maximum number of keys to return
            
        Returns:
            Dictionary containing 'Contents' (files) and 'CommonPrefixes' (folders)
        """
        bucket_name = bucket or self.bucket
        
        try:
            response = self.client.list_objects(
                Bucket=bucket_name,
                Prefix=prefix,
                Delimiter=delimiter,
                MaxKeys=max_keys
            )
            return response
        except (CosServiceError, CosClientError) as e:
            logger.error(f"Failed to list objects in COS: {str(e)}")
            raise
    
    def delete_object(self, 
                     cos_path: str,
                     bucket: str = None) -> Dict[str, Any]:
        """
        Delete an object from COS.
        
        Args:
            cos_path: Path of the file in COS to delete
            bucket: Bucket name (optional, uses instance default if not specified)
            
        Returns:
            Response dictionary from COS API
        """
        # Remove leading slash if present
        if cos_path.startswith('/'):
            cos_path = cos_path[1:]
            
        bucket_name = bucket or self.bucket
        
        try:
            response = self.client.delete_object(
                Bucket=bucket_name,
                Key=cos_path
            )
            logger.info(f"Deleted cos://{bucket_name}/{cos_path}")
            return response
        except (CosServiceError, CosClientError) as e:
            logger.error(f"Failed to delete object from COS: {str(e)}")
            raise
    
    def get_object_url(self, 
                      cos_path: str,
                      bucket: str = None,
                      expires: int = 3600) -> str:
        """
        Get a pre-signed URL for an object that expires after the specified time.
        
        Args:
            cos_path: Path of the file in COS
            bucket: Bucket name (optional, uses instance default if not specified)
            expires: URL expiration time in seconds, default is 3600 (1 hour)
            
        Returns:
            Pre-signed URL as string
        """
        # Remove leading slash if present
        if cos_path.startswith('/'):
            cos_path = cos_path[1:]
            
        bucket_name = bucket or self.bucket
        
        try:
            url = self.client.get_presigned_url(
                Method='GET',
                Bucket=bucket_name,
                Key=cos_path,
                Expired=expires
            )
            return url
        except (CosServiceError, CosClientError) as e:
            logger.error(f"Failed to get object URL from COS: {str(e)}")
            raise
    
    def check_object_exists(self, 
                           cos_path: str,
                           bucket: str = None) -> bool:
        """
        Check if an object exists in COS.
        
        Args:
            cos_path: Path of the file in COS
            bucket: Bucket name (optional, uses instance default if not specified)
            
        Returns:
            True if object exists, False otherwise
        """
        # Remove leading slash if present
        if cos_path.startswith('/'):
            cos_path = cos_path[1:]
            
        bucket_name = bucket or self.bucket
        
        try:
            self.client.head_object(
                Bucket=bucket_name,
                Key=cos_path
            )
            return True
        except CosServiceError as e:
            if e.get_status_code() == 404:
                return False
            else:
                logger.error(f"Error checking if object exists: {str(e)}")
                raise
        except CosClientError as e:
            logger.error(f"Client error checking if object exists: {str(e)}")
            raise


# Helper functions for direct use
def get_cos_client(secret_id: str = None, 
                  secret_key: str = None,
                  region: str = DEFAULT_REGION,
                  bucket: str = DEFAULT_BUCKET) -> TencentCosClient:
    """
    Get a TencentCosClient instance with the specified parameters.
    
    Args:
        secret_id: Tencent Cloud API Secret ID
        secret_key: Tencent Cloud API Secret Key
        region: COS bucket region
        bucket: COS bucket name
        
    Returns:
        TencentCosClient instance
    """
    return TencentCosClient(secret_id, secret_key, region, bucket)


def upload_file(local_path: str, 
                cos_path: str = None, 
                bucket: str = DEFAULT_BUCKET,
                region: str = DEFAULT_REGION,
                secret_id: str = None,
                secret_key: str = None) -> Dict[str, Any]:
    """
    Helper function to upload a file to COS without creating a client instance.
    
    Args:
        local_path: Path to the local file to upload
        cos_path: Path in COS where the file will be stored
        bucket: Bucket name
        region: COS bucket region
        secret_id: Tencent Cloud API Secret ID
        secret_key: Tencent Cloud API Secret Key
        
    Returns:
        Response dictionary from COS API
    """
    client = get_cos_client(secret_id, secret_key, region, bucket)
    return client.upload_file(local_path, cos_path)


def download_file(cos_path: str, 
                 local_path: str,
                 bucket: str = DEFAULT_BUCKET,
                 region: str = DEFAULT_REGION,
                 secret_id: str = None,
                 secret_key: str = None) -> Dict[str, Any]:
    """
    Helper function to download a file from COS without creating a client instance.
    
    Args:
        cos_path: Path of the file in COS
        local_path: Local path where the file will be saved
        bucket: Bucket name
        region: COS bucket region
        secret_id: Tencent Cloud API Secret ID
        secret_key: Tencent Cloud API Secret Key
        
    Returns:
        Response dictionary from COS API
    """
    client = get_cos_client(secret_id, secret_key, region, bucket)
    return client.download_file(cos_path, local_path)